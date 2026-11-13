// Mock TouchDesigner host for CHOP plugins: see ew_td_host.h for the C API and README.md for what is mimicked.
// The host loads the operator DLL with LoadLibrary (it does not link the operators), creates an instance as
// TouchDesigner does (CreateCHOPInstance, setupParameters) and cooks it in the order of CHOP_CPlusPlusBase.h:
//   pulsePressed (queued pulses), getGeneralInfo, getOutputInfo, getChannelName x channels, execute,
//   getNumInfoCHOPChans / getInfoCHOPChan, getInfoDATSize / getInfoDATEntries, getInfoPopupString, getWarningString,
//   getErrorString.
// Every call into the plugin goes through `guarded`, which turns a structured exception (access violation, ...) or a
// C++ exception that escapes the plugin into an error code and a message instead of ending the process.
#include "ew_td_host.h"

#include <windows.h>
#include <crtdbg.h>
#include <malloc.h>
#include <cctype>
#include <csignal>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <exception>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include "CHOP_CPlusPlusBase.h"

using namespace TD;

namespace {

// ---- text of the host, state of a loaded plugin ----------------------------------------------------------------------

struct Par {
    std::string name, label, page;
    int kind = EWH_PAR_FLOAT;
    int size = 1;
    double def[4] = {}, minv[4] = {}, maxv[4] = {}, smin[4] = {}, smax[4] = {};
    int cmin[4] = {}, cmax[4] = {};
    double value[4] = {};  // menu: value[0] is the index of the selected item
    std::string sdef, svalue;
    mutable std::string formatted;  // getParString of a numeric parameter
    std::vector<std::string> menuNames, menuLabels;
    bool enabled = true;
};

// An image given to the host for a TOP input: rows top-down as a numpy array holds them, pixels interleaved. 8-bit fixed
// or 32-bit float, 1, 2 or 4 channels (a 3-channel image is padded with an opaque alpha: TouchDesigner has no 3-channel
// textures).
struct TopImage {
    int width = 0, height = 0, channels = 1;
    bool isFloat = false;
    std::vector<unsigned char> bytes;
};

struct Result {
    int numChannels = 0, numSamples = 0;
    double sampleRate = 0, startIndex = 0;
    int timeslice = 0, declared = 0, matchIndex = 0;
    std::vector<float> data;
    std::vector<std::string> names;
    std::string warning, error, popup;
    std::vector<std::pair<std::string, float>> infoChop;
    bool hasDat = false;
    int datRows = 0, datCols = 0;
    std::vector<std::string> datCells;  // row-major
};

}  // namespace

struct EwHost {
    HMODULE module = nullptr;
    void (*fill)(CHOP_PluginInfo*) = nullptr;
    CHOP_CPlusPlusBase* (*create)(const OP_NodeInfo*) = nullptr;
    void (*destroy)(CHOP_CPlusPlusBase*) = nullptr;

    std::string path, pluginDir;
    std::string lastError;
    std::string pType, pLabel, pIcon, pAuthor, pEmail;
    int minInputs = 0, maxInputs = 0, apiVersion = 0, major = 0, minor = 0;

    CHOP_CPlusPlusBase* instance = nullptr;
    OP_NodeInfo node{};
    std::string nodePath;
    int cookCount = 0;
    int instanceCount = 0;
    std::vector<Par> pars;
    std::string setupIssues;
    std::vector<std::string> pulses;
    std::map<int, std::shared_ptr<TopImage>> tops;           // TOP inputs given for the next cook, by input index
    std::map<std::string, std::shared_ptr<TopImage>> parTops;  // TOPs given to TOP parameters for the next cook, by name

    std::vector<std::string> hostErrors;  // misuse of the host API during the current cook
    Result res;

    void hostError(const std::string& message) {
        for (const std::string& m : hostErrors)
            if (m == message) return;
        hostErrors.push_back(message);
    }
    Par* find(const char* name) {
        for (Par& p : pars)
            if (p.name == (name ? name : "")) return &p;
        return nullptr;
    }
};

namespace {

// ---- guarded calls into the plugin -----------------------------------------------------------------------------------

constexpr DWORD kTerminateCode = 0xE0EB0001;
constexpr DWORD kAbortCode = 0xE0EB0002;
constexpr DWORD kInvalidParameterCode = 0xE0EB0003;

struct SehInfo {
    DWORD code = 0;
    ULONG_PTR kind = 0, address = 0;
};

int captureSeh(EXCEPTION_POINTERS* ep, SehInfo* out) {
    const EXCEPTION_RECORD* r = ep->ExceptionRecord;
    out->code = r->ExceptionCode;
    if (r->ExceptionCode == EXCEPTION_ACCESS_VIOLATION && r->NumberParameters >= 2) {
        out->kind = r->ExceptionInformation[0];
        out->address = r->ExceptionInformation[1];
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

// Only plain C locals here: __try cannot live in a function with objects that need unwinding.
bool sehRun(void (*fn)(void*), void* context, SehInfo* info) {
    __try {
        fn(context);
        return true;
    } __except (captureSeh(GetExceptionInformation(), info)) {
        if (info->code == EXCEPTION_STACK_OVERFLOW) _resetstkoflw();
        return false;
    }
}

std::string describeSeh(const SehInfo& s) {
    char buffer[160];
    switch (s.code) {
        case EXCEPTION_ACCESS_VIOLATION:
            std::snprintf(buffer, sizeof buffer, "access violation (%s address 0x%llx)",
                          s.kind == 0 ? "reading" : s.kind == 1 ? "writing" : "executing",
                          static_cast<unsigned long long>(s.address));
            return buffer;
        case EXCEPTION_STACK_OVERFLOW: return "stack overflow";
        case EXCEPTION_INT_DIVIDE_BY_ZERO: return "integer division by zero";
        case EXCEPTION_ILLEGAL_INSTRUCTION: return "illegal instruction";
        case EXCEPTION_ARRAY_BOUNDS_EXCEEDED: return "array bounds exceeded";
        case 0xC0000374: return "heap corruption detected";
        case 0xC0000409: return "stack buffer overrun / fast fail";
        case kTerminateCode: return "std::terminate called (an exception left a noexcept function or was not caught)";
        case kAbortCode: return "abort() called";
        case kInvalidParameterCode: return "invalid parameter passed to a CRT function";
        default: std::snprintf(buffer, sizeof buffer, "structured exception 0x%08lX", static_cast<unsigned long>(s.code));
    }
    return buffer;
}

// Runs f(); false (with the reason in host.lastError) when the plugin faulted.
template <class F>
bool guarded(EwHost& host, const char* stage, F&& f) {
    struct Thunk {
        F* f;
        bool threw;
        std::string what;
    } thunk{&f, false, {}};
    auto trampoline = [](void* p) {
        Thunk* t = static_cast<Thunk*>(p);
        try {
            (*t->f)();
        } catch (const std::exception& e) {
            t->threw = true;
            t->what = std::string("C++ exception escaped the plugin: ") + e.what();
        } catch (...) {
            t->threw = true;
            t->what = "C++ exception of unknown type escaped the plugin";
        }
    };
    SehInfo info;
    const bool ok = sehRun(trampoline, &thunk, &info);
    if (!ok) {
        host.lastError = std::string("operator fault in ") + stage + ": " + describeSeh(info);
        return false;
    }
    if (thunk.threw) {
        host.lastError = std::string("operator fault in ") + stage + ": " + thunk.what;
        return false;
    }
    return true;
}

// The CRT resets the SIGABRT handler to the default each time it runs: arm it again before raising.
void onAbort(int) {
    std::signal(SIGABRT, onAbort);
    RaiseException(kAbortCode, 0, 0, nullptr);
}

void installFaultHandlers() {
    static bool done = false;
    if (done) return;
    done = true;
    // terminate / abort / CRT invalid-parameter checks end the process by default; make them structured exceptions
    // so that `guarded` reports them. (A __fastfail, e.g. a /GS buffer overrun, cannot be intercepted.)
    std::set_terminate([] { RaiseException(kTerminateCode, 0, 0, nullptr); });
    std::signal(SIGABRT, onAbort);
    _set_abort_behavior(0, _WRITE_ABORT_MSG | _CALL_REPORTFAULT);
    _set_invalid_parameter_handler([](const wchar_t*, const wchar_t*, const wchar_t*, unsigned, uintptr_t) {
        RaiseException(kInvalidParameterCode, 0, 0, nullptr);
    });
}

// ---- OP_String and the parameter manager ---------------------------------------------------------------------------

class HostString : public OP_String {
public:
    HostString() = default;
    void setString(const char* value) override {
        text = value ? value : "";
        touched = true;
    }
    std::string text;
    bool touched = false;
};

bool validParName(const char* name, std::string& why) {
    if (!name || !*name) { why = "empty name"; return false; }
    if (name[0] < 'A' || name[0] > 'Z') { why = "must begin with a capital letter"; return false; }
    for (const char* c = name; *c; ++c)
        if (!std::isalnum(static_cast<unsigned char>(*c))) { why = "only letters and digits are allowed"; return false; }
    return true;
}

class HostParams : public OP_ParameterManager {
public:
    explicit HostParams(EwHost& host) : host_(host) {}

    OP_ParAppendResult appendFloat(const OP_NumericParameter& np, int32_t size = 1) override { return numeric(np, EWH_PAR_FLOAT, size, "appendFloat"); }
    OP_ParAppendResult appendInt(const OP_NumericParameter& np, int32_t size = 1) override { return numeric(np, EWH_PAR_INT, size, "appendInt"); }
    OP_ParAppendResult appendXY(const OP_NumericParameter& np) override { return numeric(np, EWH_PAR_FLOAT, 2, "appendXY"); }
    OP_ParAppendResult appendXYZ(const OP_NumericParameter& np) override { return numeric(np, EWH_PAR_FLOAT, 3, "appendXYZ"); }
    OP_ParAppendResult appendUV(const OP_NumericParameter& np) override { return numeric(np, EWH_PAR_FLOAT, 2, "appendUV"); }
    OP_ParAppendResult appendUVW(const OP_NumericParameter& np) override { return numeric(np, EWH_PAR_FLOAT, 3, "appendUVW"); }
    OP_ParAppendResult appendRGB(const OP_NumericParameter& np) override { return numeric(np, EWH_PAR_FLOAT, 3, "appendRGB"); }
    OP_ParAppendResult appendRGBA(const OP_NumericParameter& np) override { return numeric(np, EWH_PAR_FLOAT, 4, "appendRGBA"); }
    OP_ParAppendResult appendXYZW(const OP_NumericParameter& np) override { return numeric(np, EWH_PAR_FLOAT, 4, "appendXYZW"); }
    OP_ParAppendResult appendWH(const OP_NumericParameter& np) override { return numeric(np, EWH_PAR_FLOAT, 2, "appendWH"); }
    OP_ParAppendResult appendToggle(const OP_NumericParameter& np) override { return numeric(np, EWH_PAR_TOGGLE, 1, "appendToggle"); }
    OP_ParAppendResult appendPulse(const OP_NumericParameter& np) override { return numeric(np, EWH_PAR_PULSE, 1, "appendPulse"); }
    OP_ParAppendResult appendMomentary(const OP_NumericParameter& np) override { return numeric(np, EWH_PAR_PULSE, 1, "appendMomentary"); }
    OP_ParAppendResult appendDynamicMenu(const OP_NumericParameter& np) override {
        issue("warning", np.name, "dynamic menu: buildDynamicMenu is not called by the host, the menu stays empty");
        return numeric(np, EWH_PAR_MENU, 1, "appendDynamicMenu");
    }

    OP_ParAppendResult appendString(const OP_StringParameter& sp) override { return string(sp, EWH_PAR_STRING, "appendString"); }
    OP_ParAppendResult appendFile(const OP_StringParameter& sp) override { return string(sp, EWH_PAR_STRING, "appendFile"); }
    OP_ParAppendResult appendFileSave(const OP_StringParameter& sp) override { return string(sp, EWH_PAR_STRING, "appendFileSave"); }
    OP_ParAppendResult appendFolder(const OP_StringParameter& sp) override { return string(sp, EWH_PAR_STRING, "appendFolder"); }
    OP_ParAppendResult appendHeader(const OP_StringParameter& sp) override { return string(sp, EWH_PAR_STRING, "appendHeader"); }
    OP_ParAppendResult appendDAT(const OP_StringParameter& sp) override { return reference(sp, "appendDAT"); }
    OP_ParAppendResult appendCHOP(const OP_StringParameter& sp) override { return reference(sp, "appendCHOP"); }
    OP_ParAppendResult appendTOP(const OP_StringParameter& sp) override { return reference(sp, "appendTOP"); }
    OP_ParAppendResult appendObject(const OP_StringParameter& sp) override { return reference(sp, "appendObject"); }
    OP_ParAppendResult appendSOP(const OP_StringParameter& sp) override { return reference(sp, "appendSOP"); }
    OP_ParAppendResult appendPOP(const OP_StringParameter& sp) override { return reference(sp, "appendPOP"); }
    OP_ParAppendResult appendPython(const OP_StringParameter& sp) override { return reference(sp, "appendPython"); }
    OP_ParAppendResult appendOP(const OP_StringParameter& sp) override { return reference(sp, "appendOP"); }
    OP_ParAppendResult appendCOMP(const OP_StringParameter& sp) override { return reference(sp, "appendCOMP"); }
    OP_ParAppendResult appendMAT(const OP_StringParameter& sp) override { return reference(sp, "appendMAT"); }
    OP_ParAppendResult appendPanelCOMP(const OP_StringParameter& sp) override { return reference(sp, "appendPanelCOMP"); }
    OP_ParAppendResult appendDynamicStringMenu(const OP_StringParameter& sp) override {
        issue("warning", sp.name, "dynamic menu: buildDynamicMenu is not called by the host, the menu stays empty");
        return string(sp, EWH_PAR_STRING, "appendDynamicStringMenu");
    }

    OP_ParAppendResult appendMenu(const OP_StringParameter& sp, int32_t n, const char** names, const char** labels) override {
        return menu(sp, n, names, labels, EWH_PAR_MENU, "appendMenu");
    }
    OP_ParAppendResult appendStringMenu(const OP_StringParameter& sp, int32_t n, const char** names, const char** labels) override {
        return menu(sp, n, names, labels, EWH_PAR_STRING, "appendStringMenu");
    }

private:
    void issue(const char* level, const char* name, const std::string& message) {
        host_.setupIssues += std::string(level) + ": " + (name ? name : "(null)") + ": " + message + "\n";
    }

    Par* declare(const char* name, const char* label, const char* page, int kind, const char* call) {
        std::string why;
        if (!validParName(name, why)) {
            issue("error", name, std::string(call) + ": invalid parameter name (" + why + ")");
            return nullptr;
        }
        if (host_.find(name)) {
            issue("error", name, std::string(call) + ": duplicate parameter name");
            return nullptr;
        }
        for (const char* c = name + 1; *c; ++c)
            if (*c >= 'A' && *c <= 'Z') {
                issue("warning", name, "capital letter after the first: TouchDesigner custom parameter names are a capital "
                                       "followed by lowercase letters and digits (it may be renamed or refused)");
                break;
            }
        host_.pars.emplace_back();
        Par& p = host_.pars.back();
        p.name = name;
        p.label = label ? label : name;
        p.page = page ? page : "Custom";
        p.kind = kind;
        return &p;
    }

    OP_ParAppendResult numeric(const OP_NumericParameter& np, int kind, int size, const char* call) {
        if (size < 1 || size > 4) {
            issue("error", np.name, std::string(call) + ": size out of range");
            return OP_ParAppendResult::InvalidSize;
        }
        Par* p = declare(np.name, np.label, np.page, kind, call);
        if (!p) return OP_ParAppendResult::InvalidName;
        p->size = size;
        for (int i = 0; i < 4; ++i) {
            p->def[i] = np.defaultValues[i];
            p->minv[i] = np.minValues[i];
            p->maxv[i] = np.maxValues[i];
            p->smin[i] = np.minSliders[i];
            p->smax[i] = np.maxSliders[i];
            p->cmin[i] = np.clampMins[i];
            p->cmax[i] = np.clampMaxes[i];
            p->value[i] = i < size ? np.defaultValues[i] : 0.0;
        }
        if (kind == EWH_PAR_TOGGLE) p->value[0] = p->def[0] = p->def[0] != 0.0 ? 1.0 : 0.0;
        if (kind == EWH_PAR_PULSE) p->value[0] = 0.0;
        return OP_ParAppendResult::Success;
    }

    OP_ParAppendResult string(const OP_StringParameter& sp, int kind, const char* call) {
        Par* p = declare(sp.name, sp.label, sp.page, kind, call);
        if (!p) return OP_ParAppendResult::InvalidName;
        p->sdef = p->svalue = sp.defaultValue ? sp.defaultValue : "";
        return OP_ParAppendResult::Success;
    }

    OP_ParAppendResult reference(const OP_StringParameter& sp, const char* call) {
        issue("warning", sp.name, std::string(call) + ": reference parameter, the host keeps the path as a string and does not resolve it");
        return string(sp, EWH_PAR_STRING, call);
    }

    OP_ParAppendResult menu(const OP_StringParameter& sp, int n, const char** names, const char** labels, int kind, const char* call) {
        Par* p = declare(sp.name, sp.label, sp.page, kind, call);
        if (!p) return OP_ParAppendResult::InvalidName;
        for (int i = 0; i < n; ++i) {
            p->menuNames.push_back(names && names[i] ? names[i] : "");
            p->menuLabels.push_back(labels && labels[i] ? labels[i] : "");
        }
        p->sdef = p->svalue = sp.defaultValue ? sp.defaultValue : "";
        if (kind == EWH_PAR_MENU) {
            int index = -1;
            for (int i = 0; i < n; ++i)
                if (p->menuNames[i] == p->sdef) index = i;
            if (index < 0) {
                issue("error", sp.name, std::string(call) + ": default value '" + p->sdef + "' is not an item of the menu");
                index = 0;
                p->sdef = p->svalue = n > 0 ? p->menuNames[0] : "";
            }
            p->value[0] = p->def[0] = index;
        }
        return OP_ParAppendResult::Success;
    }

    EwHost& host_;
};

// ---- TOP inputs: pixel formats, conversion, downloadTexture ---------------------------------------------------------------

OP_PixelFormat nativeFormat(const TopImage& img) {
    if (img.isFloat) return img.channels == 1 ? OP_PixelFormat::Mono32Float : img.channels == 2 ? OP_PixelFormat::RG32Float : OP_PixelFormat::RGBA32Float;
    return img.channels == 1 ? OP_PixelFormat::Mono8Fixed : img.channels == 2 ? OP_PixelFormat::RG8Fixed : OP_PixelFormat::RGBA8Fixed;
}

struct FormatLayout {
    int channels = 0, bytesPerChannel = 0;
    bool isFloat = false, bgr = false;
};

bool layoutOf(OP_PixelFormat f, FormatLayout& l) {
    switch (f) {
        case OP_PixelFormat::Mono8Fixed: l = {1, 1, false, false}; return true;
        case OP_PixelFormat::RG8Fixed: l = {2, 1, false, false}; return true;
        case OP_PixelFormat::RGBA8Fixed: l = {4, 1, false, false}; return true;
        case OP_PixelFormat::BGRA8Fixed: l = {4, 1, false, true}; return true;
        case OP_PixelFormat::Mono16Fixed: l = {1, 2, false, false}; return true;
        case OP_PixelFormat::RG16Fixed: l = {2, 2, false, false}; return true;
        case OP_PixelFormat::RGBA16Fixed: l = {4, 2, false, false}; return true;
        case OP_PixelFormat::Mono32Float: l = {1, 4, true, false}; return true;
        case OP_PixelFormat::RG32Float: l = {2, 4, true, false}; return true;
        case OP_PixelFormat::RGBA32Float: l = {4, 4, true, false}; return true;
        default: return false;
    }
}

// The image in the requested format. Row 0 of the result is the top row of the image when `flip` (verticalFlip = true) and
// the bottom row otherwise: TouchDesigner textures have their origin at the bottom left, so the first row in memory is the
// bottom one unless the download is flipped. Channels: a 1-channel image reads as (r, r, r, 1), a 2-channel one as
// (r, g, 0, 1); Mono takes r, RG takes r and g. Fixed point values are v * (2^bits - 1) rounded, float is stored as is.
std::vector<unsigned char> convertImage(const TopImage& img, const FormatLayout& l, bool flip) {
    const int w = img.width, h = img.height;
    std::vector<unsigned char> out(static_cast<size_t>(w) * h * l.channels * l.bytesPerChannel);
    const size_t srcPixel = static_cast<size_t>(img.channels) * (img.isFloat ? 4 : 1);
    for (int r = 0; r < h; ++r) {
        const int srcRow = flip ? r : h - 1 - r;
        for (int x = 0; x < w; ++x) {
            const unsigned char* p = img.bytes.data() + (static_cast<size_t>(srcRow) * w + x) * srcPixel;
            float v[4] = {0.f, 0.f, 0.f, 0.f};
            for (int c = 0; c < img.channels; ++c) {
                if (img.isFloat) std::memcpy(&v[c], p + 4 * c, 4);
                else v[c] = static_cast<float>(p[c]) / 255.f;
            }
            float rgba[4];
            if (img.channels == 1) { rgba[0] = rgba[1] = rgba[2] = v[0]; rgba[3] = 1.f; }
            else if (img.channels == 2) { rgba[0] = v[0]; rgba[1] = v[1]; rgba[2] = 0.f; rgba[3] = 1.f; }
            else { std::memcpy(rgba, v, sizeof rgba); }
            static const int kRgba[4] = {0, 1, 2, 3}, kBgra[4] = {2, 1, 0, 3};
            const int* order = l.bgr ? kBgra : kRgba;
            unsigned char* dst = out.data() + (static_cast<size_t>(r) * w + x) * l.channels * l.bytesPerChannel;
            for (int c = 0; c < l.channels; ++c) {
                const float value = rgba[order[c]];
                if (l.isFloat) {
                    std::memcpy(dst + 4 * c, &value, 4);
                } else {
                    const float clamped = std::isnan(value) ? 0.f : value < 0.f ? 0.f : value > 1.f ? 1.f : value;
                    const unsigned maxValue = l.bytesPerChannel == 1 ? 255u : 65535u;
                    const unsigned q = static_cast<unsigned>(clamped * static_cast<float>(maxValue) + 0.5f);
                    if (l.bytesPerChannel == 1) {
                        dst[c] = static_cast<unsigned char>(q);
                    } else {
                        dst[2 * c] = static_cast<unsigned char>(q & 255u);
                        dst[2 * c + 1] = static_cast<unsigned char>(q >> 8);
                    }
                }
            }
        }
    }
    return out;
}

class HostDownload : public OP_TOPDownloadResult {
public:
    HostDownload(std::vector<unsigned char> data, const OP_TextureDesc& desc) : bytes_(std::move(data)) {
        size = bytes_.size();
        textureDesc = desc;
        colorSpace = OP_ColorSpace::Passthrough;
    }
    void* getData() override { return bytes_.data(); }
    void acquire() override { ++refs_; }
    void release() override {
        if (--refs_ == 0) delete this;
    }
    void reserved0() override {}
    void reserved1() override {}
    void reserved2() override {}
    void reserved3() override {}
    void reserved4() override {}

private:
    std::vector<unsigned char> bytes_;
    int refs_ = 1;
};

class HostTop : public OP_TOPInput {
public:
    HostTop(EwHost& host, std::shared_ptr<TopImage> image, std::string path, uint32_t id, int64_t cooks)
        : host_(host), image_(std::move(image)), path_(std::move(path)) {
        opPath = path_.c_str();
        opId = id;
        textureDesc.width = static_cast<uint32_t>(image_->width);
        textureDesc.height = static_cast<uint32_t>(image_->height);
        textureDesc.depth = 1;
        textureDesc.texDim = OP_TexDim::e2D;
        textureDesc.pixelFormat = nativeFormat(*image_);
        totalCooks = cooks;
        customOP = nullptr;
    }

    OP_SmartRef<OP_TOPDownloadResult> downloadTexture(const OP_TOPInputDownloadOptions& opts, void*) const override {
        OP_SmartRef<OP_TOPDownloadResult> result;
        const OP_PixelFormat target = opts.pixelFormat == OP_PixelFormat::Invalid ? textureDesc.pixelFormat : opts.pixelFormat;
        FormatLayout layout;
        if (!layoutOf(target, layout)) {
            host_.hostError("downloadTexture: pixel format " + std::to_string(static_cast<int>(target)) +
                            " is not implemented by the mock host");
            return result;
        }
        OP_TextureDesc desc = textureDesc;
        desc.pixelFormat = target;
        result.takeOwnership(new HostDownload(convertImage(*image_, layout, opts.verticalFlip), desc));
        return result;
    }
    const OP_CUDAArrayInfo* getCUDAArray(const OP_CUDAAcquireInfo&, void*) const override {
        host_.hostError("the operator called OP_TOPInput::getCUDAArray, which the mock host does not implement");
        return nullptr;
    }

private:
    void* reserved0() override { return nullptr; }
    void* reserved1() override { return nullptr; }
    void* reserved2() override { return nullptr; }
    void* reserved3() override { return nullptr; }
    void* reserved4() override { return nullptr; }

    EwHost& host_;
    std::shared_ptr<TopImage> image_;
    std::string path_;
};

// ---- OP_Inputs --------------------------------------------------------------------------------------------------------

std::string formatNumber(double v) {
    char buffer[40];
    std::snprintf(buffer, sizeof buffer, "%g", v);
    return buffer;
}

class HostInputs : public OP_Inputs {
public:
    HostInputs(EwHost& host, const EwInput* inputs, int count, double rate, double startIndex,
               const std::map<int, std::shared_ptr<TopImage>>& tops,
               const std::map<std::string, std::shared_ptr<TopImage>>& parTops)
        : host_(host) {
        int last = -1;
        for (int i = 0; i < count; ++i)
            if (inputs[i].connected) last = i;
        for (const auto& t : tops) last = t.first > last ? t.first : last;
        count_ = last + 1;  // TouchDesigner counts up to the last connected input
        chops_.resize(count_);
        tops_.resize(count_);
        channelData_.resize(count_);
        nameData_.resize(count_);
        nameText_.resize(count_);
        paths_.resize(count_);
        for (int i = 0; i < count_; ++i) {
            const auto top = tops.find(i);
            if (top != tops.end()) {
                tops_[i] = std::make_unique<HostTop>(host, top->second, "/project1/top" + std::to_string(i + 1), 2000 + i, host.cookCount);
                connected_.push_back(false);  // a TOP slot has no CHOP: getInputCHOP gives nullptr
                continue;
            }
            const bool chopHere = i < count && inputs[i].connected;
            connected_.push_back(chopHere);
            if (!chopHere) continue;
            const EwInput& in = inputs[i];
            paths_[i] = "/project1/in" + std::to_string(i + 1);
            OP_CHOPInput& c = chops_[i];
            std::memset(&c, 0, sizeof c);
            c.opPath = paths_[i].c_str();
            c.opId = 1000 + i;
            c.numChannels = in.channels;
            c.numSamples = in.samples;
            c.sampleRate = in.sample_rate > 0 ? in.sample_rate : rate;
            c.startIndex = startIndex;
            for (int ch = 0; ch < in.channels; ++ch) {
                static const float kNone = 0.f;
                channelData_[i].push_back(in.data && in.samples > 0 ? in.data + static_cast<size_t>(ch) * in.samples : &kNone);
                nameText_[i].push_back(in.names && in.names[ch] ? in.names[ch] : "chan" + std::to_string(ch + 1));
            }
            for (const std::string& s : nameText_[i]) nameData_[i].push_back(s.c_str());
            c.channelData = channelData_[i].data();
            c.nameData = nameData_[i].data();
        }
        uint32_t parId = 3000;
        for (const auto& t : parTops)
            parTops_[t.first] = std::make_unique<HostTop>(host, t.second, "/project1/" + t.first, parId++, host.cookCount);
        std::memset(&time_, 0, sizeof time_);
        time_.rate = time_.rootRate = rate;
        time_.deltaFrames = host.cookCount > 1 ? 1.0 : 0.0;
        time_.deltaMS = time_.deltaFrames * 1000.0 / rate;
        time_.absFrame = host.cookCount;
        time_.frame = time_.rootFrame = host.cookCount;
    }

    void setTotalCooks(int64_t cooks) {
        for (OP_CHOPInput& c : chops_) c.totalCooks = cooks;
    }
    const OP_CHOPInput* chop(int i) const { return i >= 0 && i < count_ && connected_[i] ? &chops_[i] : nullptr; }
    const std::vector<std::string>& names(int i) const { return nameText_[i]; }

    int32_t getNumInputs() const override { return count_; }
    const OP_CHOPInput* getInputCHOP(int32_t index) const override { return chop(index); }

    double getParDouble(const char* name, int32_t index = 0) const override {
        const Par* p = par(name);
        if (!p) return 0.0;
        if (p->kind == EWH_PAR_STRING) return std::atof(p->svalue.c_str());
        if (index < 0 || index >= p->size) {
            host_.hostError(std::string("getParDouble('") + name + "', " + std::to_string(index) + "): index out of range (size " +
                            std::to_string(p->size) + ")");
            return 0.0;
        }
        return p->value[index];
    }
    int32_t getParInt(const char* name, int32_t index = 0) const override {
        const Par* p = par(name);
        if (!p) return 0;
        if (p->kind == EWH_PAR_STRING) return static_cast<int32_t>(std::atof(p->svalue.c_str()));
        if (index < 0 || index >= p->size) {
            host_.hostError(std::string("getParInt('") + name + "', " + std::to_string(index) + "): index out of range (size " +
                            std::to_string(p->size) + ")");
            return 0;
        }
        return static_cast<int32_t>(p->value[index]);  // a float parameter truncates, as in TouchDesigner
    }
    const char* getParString(const char* name) const override {
        const Par* p = par(name);
        if (!p) return "";
        if (p->kind == EWH_PAR_STRING || p->kind == EWH_PAR_MENU) return p->svalue.c_str();
        p->formatted = formatNumber(p->value[0]);
        return p->formatted.c_str();
    }
    const char* getParFilePath(const char* name) const override { return getParString(name); }

    bool getParDouble2(const char* n, double& a, double& b) const override { return multi(n, 2, {&a, &b}); }
    bool getParDouble3(const char* n, double& a, double& b, double& c) const override { return multi(n, 3, {&a, &b, &c}); }
    bool getParDouble4(const char* n, double& a, double& b, double& c, double& d) const override { return multi(n, 4, {&a, &b, &c, &d}); }
    bool getParRGB(const char* n, double& r, double& g, double& b) const override { return multi(n, 3, {&r, &g, &b}); }
    bool getParRGBA(const char* n, double& r, double& g, double& b, double& a) const override { return multi(n, 4, {&r, &g, &b, &a}); }
    bool getParInt2(const char* n, int32_t& a, int32_t& b) const override { return multiInt(n, 2, {&a, &b}); }
    bool getParInt3(const char* n, int32_t& a, int32_t& b, int32_t& c) const override { return multiInt(n, 3, {&a, &b, &c}); }
    bool getParInt4(const char* n, int32_t& a, int32_t& b, int32_t& c, int32_t& d) const override { return multiInt(n, 4, {&a, &b, &c, &d}); }

    void enablePar(const char* name, bool onoff) const override {
        if (Par* p = host_.find(name)) p->enabled = onoff;
        else host_.hostError(std::string("enablePar('") + (name ? name : "") + "'): no such parameter");
    }
    const OP_TimeInfo* getTimeInfo() const override { return &time_; }

    // What operators of this repository do not use: the host says so instead of returning something plausible.
    const OP_DATInput* getParDAT(const char*) const override { return unsupported("getParDAT"); }
    const OP_CHOPInput* getParCHOP(const char*) const override { return unsupported("getParCHOP"); }
    const OP_ObjectInput* getParObject(const char*) const override { return unsupported("getParObject"); }
    const OP_DATInput* getDAT(const char*) const override { return unsupported("getDAT"); }
    const OP_CHOPInput* getCHOP(const char*) const override { return unsupported("getCHOP"); }
    const OP_ObjectInput* getObject(const char*) const override { return unsupported("getObject"); }
    const OP_SOPInput* getParSOP(const char*) const override { return unsupported("getParSOP"); }
    const OP_SOPInput* getInputSOP(int32_t) const override { return unsupported("getInputSOP"); }
    const OP_SOPInput* getSOP(const char*) const override { return unsupported("getSOP"); }
    const OP_DATInput* getInputDAT(int32_t) const override { return unsupported("getInputDAT"); }
    PyObject* getParPython(const char*) const override { return unsupported("getParPython"); }
    const OP_TOPInput* getTOP(const char*) const override { return unsupported("getTOP"); }
    const OP_TOPInput* getInputTOP(int32_t index) const override {
        return index >= 0 && index < count_ ? tops_[index].get() : nullptr;  // nullptr: the slot holds no TOP
    }
    const OP_TOPInput* getParTOP(const char* name) const override {
        if (!par(name)) return nullptr;  // not declared: an error of the operator
        const auto it = parTops_.find(name);
        return it == parTops_.end() ? nullptr : it->second.get();  // nullptr: the parameter names no TOP
    }
    const OP_POPInput* getInputPOP(int32_t) const override { return unsupported("getInputPOP"); }
    const OP_POPInput* getParPOP(const char*) const override { return unsupported("getParPOP"); }
    const OP_POPInput* getPOP(const char*) const override { return unsupported("getPOP"); }
    bool getRelativeTransform(const char*, const char*, double[4][4]) const override {
        unsupported("getRelativeTransform");
        return false;
    }

private:
    const OP_TOPInputOpenGL* getInputTOPOpenGL(int32_t) const override { return unsupported("getInputTOPOpenGL"); }
    const OP_TOPInputOpenGL* getParTOPOpenGL(const char*) const override { return unsupported("getParTOPOpenGL"); }
    const OP_TOPInputOpenGL* getTOPOpenGL(const char*) const override { return unsupported("getTOPOpenGL"); }
    void* getTOPDataInCPUMemory(const OP_TOPInputOpenGL*, const OP_TOPInputDownloadOptionsOpenGL*) const override {
        // deprecated and private in the SDK: the way to read a TOP is OP_TOPInput::downloadTexture
        return unsupported("getTOPDataInCPUMemory (deprecated; use OP_TOPInput::downloadTexture)");
    }

    std::nullptr_t unsupported(const char* function) const {
        host_.hostError(std::string("the operator called OP_Inputs::") + function + ", which the mock host does not implement");
        return nullptr;
    }
    Par* par(const char* name) const {
        Par* p = host_.find(name);
        if (!p) host_.hostError(std::string("the operator asked for the parameter '") + (name ? name : "(null)") + "', which it did not declare");
        return p;
    }
    bool multi(const char* name, int n, std::initializer_list<double*> out) const {
        const Par* p = par(name);
        if (!p || p->size < n || p->kind == EWH_PAR_STRING) return false;
        int i = 0;
        for (double* o : out) *o = p->value[i++];
        return true;
    }
    bool multiInt(const char* name, int n, std::initializer_list<int32_t*> out) const {
        const Par* p = par(name);
        if (!p || p->size < n || p->kind == EWH_PAR_STRING) return false;
        int i = 0;
        for (int32_t* o : out) *o = static_cast<int32_t>(p->value[i++]);
        return true;
    }

    EwHost& host_;
    int count_ = 0;
    std::vector<bool> connected_;
    std::vector<OP_CHOPInput> chops_;
    std::vector<std::unique_ptr<HostTop>> tops_;
    std::map<std::string, std::unique_ptr<HostTop>> parTops_;
    std::vector<std::string> paths_;
    std::vector<std::vector<const float*>> channelData_;
    std::vector<std::vector<const char*>> nameData_;
    std::vector<std::vector<std::string>> nameText_;
    OP_TimeInfo time_;
};

// ---- helpers ------------------------------------------------------------------------------------------------------------

std::wstring widen(const char* utf8) {
    const int n = MultiByteToWideChar(CP_UTF8, 0, utf8, -1, nullptr, 0);
    std::wstring w(n > 0 ? n - 1 : 0, L'\0');
    if (n > 1) MultiByteToWideChar(CP_UTF8, 0, utf8, -1, &w[0], n);
    return w;
}

void copyError(char* err, int len, const std::string& message) {
    if (!err || len <= 0) return;
    std::snprintf(err, static_cast<size_t>(len), "%s", message.c_str());
}

// CHOP_PluginInfo hides the bounds of the API versions the host accepts behind private const members that only
// TouchDesigner's own class may set; the plugin refuses to fill the info (setAPIVersion fails) if they are 0. The
// offsets are checked by static_asserts of CHOP_CPlusPlusBase.h, so the bounds are written there.
void setApiBounds(CHOP_PluginInfo* info, int32_t version) {
    const size_t base = 408 + sizeof(OP_CustomOPInfo) + 18 * 4;
    std::memcpy(reinterpret_cast<char*>(info) + base, &version, sizeof version);
    std::memcpy(reinterpret_cast<char*>(info) + base + 4, &version, sizeof version);
}

bool createInstance(EwHost& h) {
    h.pars.clear();
    h.setupIssues.clear();
    h.pulses.clear();
    h.cookCount = 0;
    h.node = OP_NodeInfo{};
    ++h.instanceCount;
    h.nodePath = "/project1/" + h.pType + std::to_string(h.instanceCount);
    h.node.opPath = h.nodePath.c_str();
    h.node.opId = 5000 + h.instanceCount;
    h.node.mainWindowHandle = nullptr;
    h.node.pluginPath = h.path.c_str();
    h.node.context = nullptr;  // calling the context is not supported
    h.node.processHInstance = GetModuleHandleW(nullptr);
    h.node.workingColorSpace = OP_WorkingColorSpace::Passthrough;

    bool created = guarded(h, "CreateCHOPInstance", [&] { h.instance = h.create(&h.node); });
    if (!created) return false;
    if (!h.instance) {
        h.lastError = "CreateCHOPInstance returned nullptr";
        return false;
    }
    HostParams manager(h);
    return guarded(h, "setupParameters", [&] { h.instance->setupParameters(&manager, nullptr); });
}

void destroyInstance(EwHost& h) {
    if (!h.instance) return;
    CHOP_CPlusPlusBase* instance = h.instance;
    h.instance = nullptr;
    guarded(h, "DestroyCHOPInstance", [&] { h.destroy(instance); });
}

}  // namespace

// ---- C API -----------------------------------------------------------------------------------------------------------------

extern "C" {

EWH_API int ewh_abi_version(void) { return EWH_ABI_VERSION; }

EWH_API EwHost* ewh_open(const char* dll_path, char* err, int err_len) {
    installFaultHandlers();
    auto host = std::make_unique<EwHost>();
    host->path = dll_path ? dll_path : "";
    host->module = LoadLibraryExW(widen(host->path.c_str()).c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!host->module) {
        copyError(err, err_len, "LoadLibrary failed for " + host->path + " (Windows error " + std::to_string(GetLastError()) + ")");
        return nullptr;
    }
    host->fill = reinterpret_cast<void (*)(CHOP_PluginInfo*)>(GetProcAddress(host->module, "FillCHOPPluginInfo"));
    host->create = reinterpret_cast<CHOP_CPlusPlusBase* (*)(const OP_NodeInfo*)>(GetProcAddress(host->module, "CreateCHOPInstance"));
    host->destroy = reinterpret_cast<void (*)(CHOP_CPlusPlusBase*)>(GetProcAddress(host->module, "DestroyCHOPInstance"));
    if (!host->fill || !host->create || !host->destroy) {
        copyError(err, err_len, host->path + " does not export FillCHOPPluginInfo, CreateCHOPInstance and DestroyCHOPInstance");
        FreeLibrary(host->module);
        return nullptr;
    }

    // FillCHOPPluginInfo
    alignas(16) static thread_local char storage[sizeof(CHOP_PluginInfo)];
    std::memset(storage, 0, sizeof storage);
    CHOP_PluginInfo* info = new (storage) CHOP_PluginInfo();
    setApiBounds(info, CHOPCPlusPlusAPIVersion);
    HostString type, label, icon, author, email, python, help;
    OP_CustomOPInfo& c = info->customOPInfo;
    c.opType = &type;
    c.opLabel = &label;
    c.opIcon = &icon;
    c.authorName = &author;
    c.authorEmail = &email;
    c.pythonVersion = &python;
    c.opHelpURL = &help;
    if (!guarded(*host, "FillCHOPPluginInfo", [&] { host->fill(info); })) {
        copyError(err, err_len, host->lastError);
        FreeLibrary(host->module);
        return nullptr;
    }
    if (!type.touched) {
        copyError(err, err_len, "FillCHOPPluginInfo did not fill the plugin info (API version " +
                                    std::to_string(CHOPCPlusPlusAPIVersion) + " refused by the plugin?)");
        FreeLibrary(host->module);
        return nullptr;
    }
    host->pType = type.text;
    host->pLabel = label.text;
    host->pIcon = icon.text;
    host->pAuthor = author.text;
    host->pEmail = email.text;
    host->minInputs = c.minInputs;
    host->maxInputs = c.maxInputs;
    host->apiVersion = info->getAPIVersion();
    host->major = c.majorVersion;
    host->minor = c.minorVersion;

    if (!createInstance(*host)) {
        copyError(err, err_len, host->lastError);
        destroyInstance(*host);
        FreeLibrary(host->module);
        return nullptr;
    }
    return host.release();
}

EWH_API void ewh_close(EwHost* host) {
    if (!host) return;
    destroyInstance(*host);
    if (host->module) FreeLibrary(host->module);
    delete host;
}

EWH_API const char* ewh_last_error(EwHost* host) { return host->lastError.c_str(); }

EWH_API const char* ewh_plugin_text(EwHost* host, int which) {
    switch (which) {
        case 0: return host->pType.c_str();
        case 1: return host->pLabel.c_str();
        case 2: return host->pIcon.c_str();
        case 3: return host->pAuthor.c_str();
        case 4: return host->pEmail.c_str();
    }
    return "";
}

EWH_API int ewh_plugin_inputs(EwHost* host, int* min_inputs, int* max_inputs) {
    *min_inputs = host->minInputs;
    *max_inputs = host->maxInputs;
    return 0;
}

EWH_API int ewh_plugin_version(EwHost* host, int* api_version, int* major, int* minor) {
    *api_version = host->apiVersion;
    *major = host->major;
    *minor = host->minor;
    return 0;
}

EWH_API int ewh_reset_instance(EwHost* host) {
    destroyInstance(*host);
    host->lastError.clear();
    if (!createInstance(*host)) return EWH_OPERATOR_FAULT;
    return EWH_OK;
}

EWH_API int ewh_param_count(EwHost* host) { return static_cast<int>(host->pars.size()); }

EWH_API int ewh_param_info(EwHost* host, int index, EwParamInfo* info) {
    if (index < 0 || index >= static_cast<int>(host->pars.size())) return -1;
    const Par& p = host->pars[index];
    std::memset(info, 0, sizeof *info);
    info->kind = p.kind;
    info->size = p.size;
    info->num_menu = static_cast<int>(p.menuNames.size());
    for (int i = 0; i < 4; ++i) {
        info->def[i] = p.def[i];
        info->min[i] = p.minv[i];
        info->max[i] = p.maxv[i];
        info->slider_min[i] = p.smin[i];
        info->slider_max[i] = p.smax[i];
        info->clamp_min[i] = p.cmin[i];
        info->clamp_max[i] = p.cmax[i];
    }
    return 0;
}

EWH_API const char* ewh_param_text(EwHost* host, int index, int which) {
    if (index < 0 || index >= static_cast<int>(host->pars.size())) return "";
    const Par& p = host->pars[index];
    switch (which) {
        case 0: return p.name.c_str();
        case 1: return p.label.c_str();
        case 2: return p.page.c_str();
        case 3: return p.sdef.c_str();
    }
    return "";
}

EWH_API const char* ewh_param_menu_name(EwHost* host, int index, int item) {
    if (index < 0 || index >= static_cast<int>(host->pars.size())) return "";
    const Par& p = host->pars[index];
    return item >= 0 && item < static_cast<int>(p.menuNames.size()) ? p.menuNames[item].c_str() : "";
}

EWH_API const char* ewh_param_menu_label(EwHost* host, int index, int item) {
    if (index < 0 || index >= static_cast<int>(host->pars.size())) return "";
    const Par& p = host->pars[index];
    return item >= 0 && item < static_cast<int>(p.menuLabels.size()) ? p.menuLabels[item].c_str() : "";
}

EWH_API const char* ewh_setup_issues(EwHost* host) { return host->setupIssues.c_str(); }

EWH_API int ewh_set_number(EwHost* host, const char* name, int index, double value) {
    Par* p = host->find(name);
    if (!p) { host->lastError = std::string("no parameter named '") + (name ? name : "") + "'"; return -1; }
    if (index < 0 || index >= p->size) { host->lastError = "parameter '" + p->name + "' has no value " + std::to_string(index); return -1; }
    if (std::isnan(value)) { host->lastError = "NaN is not a value of parameter '" + p->name + "'"; return -1; }
    switch (p->kind) {
        case EWH_PAR_STRING:
            host->lastError = "parameter '" + p->name + "' is a string, use set_string";
            return -1;
        case EWH_PAR_PULSE:
            host->lastError = "parameter '" + p->name + "' is a pulse, use pulse";
            return -1;
        case EWH_PAR_TOGGLE: value = value != 0.0 ? 1.0 : 0.0; break;
        case EWH_PAR_MENU: {
            const int n = static_cast<int>(p->menuNames.size());
            if (value != std::floor(value) || value < 0 || value >= n) {
                host->lastError = "menu '" + p->name + "' has " + std::to_string(n) + " items, index " + formatNumber(value) + " is not one";
                return -1;
            }
            p->svalue = p->menuNames[static_cast<int>(value)];
            break;
        }
        case EWH_PAR_INT: value = std::floor(value + 0.5);  // fallthrough: integers are also clamped
        default:
            if (p->cmin[index] && value < p->minv[index]) value = p->minv[index];
            if (p->cmax[index] && value > p->maxv[index]) value = p->maxv[index];
    }
    p->value[index] = value;
    return 0;
}

EWH_API int ewh_set_string(EwHost* host, const char* name, const char* value) {
    Par* p = host->find(name);
    if (!p) { host->lastError = std::string("no parameter named '") + (name ? name : "") + "'"; return -1; }
    const std::string text = value ? value : "";
    if (p->kind == EWH_PAR_STRING) {
        p->svalue = text;
        return 0;
    }
    if (p->kind == EWH_PAR_MENU) {
        for (size_t i = 0; i < p->menuNames.size(); ++i)
            if (p->menuNames[i] == text) {
                p->value[0] = static_cast<double>(i);
                p->svalue = text;
                return 0;
            }
        std::string items;
        for (const std::string& n : p->menuNames) items += (items.empty() ? "" : ", ") + n;
        host->lastError = "'" + text + "' is not an item of menu '" + p->name + "' (" + items + ")";
        return -1;
    }
    host->lastError = "parameter '" + p->name + "' is numeric, use set_number";
    return -1;
}

EWH_API int ewh_pulse(EwHost* host, const char* name) {
    Par* p = host->find(name);
    if (!p || p->kind != EWH_PAR_PULSE) {
        host->lastError = std::string("no pulse parameter named '") + (name ? name : "") + "'";
        return -1;
    }
    host->pulses.push_back(p->name);
    return 0;
}

EWH_API int ewh_get_number(EwHost* host, const char* name, int index, double* value) {
    Par* p = host->find(name);
    if (!p || index < 0 || index >= p->size) { host->lastError = std::string("no such parameter value: ") + (name ? name : ""); return -1; }
    *value = p->kind == EWH_PAR_STRING ? std::atof(p->svalue.c_str()) : p->value[index];
    return 0;
}

EWH_API const char* ewh_get_string(EwHost* host, const char* name) {
    Par* p = host->find(name);
    if (!p) { host->lastError = std::string("no parameter named '") + (name ? name : "") + "'"; return nullptr; }
    if (p->kind == EWH_PAR_STRING || p->kind == EWH_PAR_MENU) return p->svalue.c_str();
    p->formatted = formatNumber(p->value[0]);
    return p->formatted.c_str();
}

EWH_API int ewh_param_enabled(EwHost* host, const char* name) {
    const Par* p = host->find(name);
    return p ? (p->enabled ? 1 : 0) : -1;
}

}  // extern "C"

namespace {
std::shared_ptr<TopImage> makeTopImage(EwHost* host, const void* data, int width, int height, int channels, int is_float) {
    if (width < 1 || height < 1 || channels < 1 || channels > 4 || !data) {
        host->lastError = "TOP image: invalid size, channel count or data";
        return nullptr;
    }
    auto image = std::make_shared<TopImage>();
    image->width = width;
    image->height = height;
    image->isFloat = is_float != 0;
    image->channels = channels == 3 ? 4 : channels;
    const size_t element = image->isFloat ? 4 : 1;
    const size_t pixels = static_cast<size_t>(width) * height;
    image->bytes.resize(pixels * image->channels * element);
    const unsigned char* src = static_cast<const unsigned char*>(data);
    if (channels != 3) {
        std::memcpy(image->bytes.data(), src, image->bytes.size());
    } else {
        for (size_t p = 0; p < pixels; ++p) {  // RGB -> RGBA with an opaque alpha
            unsigned char* dst = image->bytes.data() + p * 4 * element;
            std::memcpy(dst, src + p * 3 * element, 3 * element);
            if (image->isFloat) {
                const float one = 1.f;
                std::memcpy(dst + 3 * element, &one, 4);
            } else {
                dst[3] = 255;
            }
        }
    }
    return image;
}
}  // namespace

extern "C" {

EWH_API int ewh_set_top_input(EwHost* host, int index, const void* data, int width, int height, int channels, int is_float) {
    if (index < 0 || index > 63) {
        host->lastError = "ewh_set_top_input: invalid input index";
        return -1;
    }
    std::shared_ptr<TopImage> image = makeTopImage(host, data, width, height, channels, is_float);
    if (!image) return -1;
    host->tops[index] = std::move(image);
    return 0;
}

EWH_API int ewh_set_top_par(EwHost* host, const char* name, const void* data, int width, int height, int channels, int is_float) {
    if (!host->find(name)) {
        host->lastError = std::string("no parameter named '") + (name ? name : "") + "'";
        return -1;
    }
    std::shared_ptr<TopImage> image = makeTopImage(host, data, width, height, channels, is_float);
    if (!image) return -1;
    host->parTops[name] = std::move(image);
    return 0;
}

EWH_API int ewh_cook(EwHost* host, const EwInput* inputs, int num_inputs, double default_rate, int timeslice_samples,
                     double start_index, float fill) {
    EwHost& h = *host;
    h.hostErrors.clear();
    h.lastError.clear();
    h.res = Result{};
    Result& r = h.res;
    const std::map<int, std::shared_ptr<TopImage>> tops = std::move(h.tops);  // TOP inputs live for one cook
    h.tops.clear();
    const std::map<std::string, std::shared_ptr<TopImage>> parTops = std::move(h.parTops);
    h.parTops.clear();
    if (!h.instance) { h.lastError = "no instance (the last reset_instance failed)"; return EWH_OPERATOR_FAULT; }
    if (!(default_rate > 0)) { h.lastError = "default_rate must be positive"; return EWH_HOST_ERROR; }
    if (num_inputs < 0 || (num_inputs > 0 && !inputs)) { h.lastError = "invalid inputs"; return EWH_HOST_ERROR; }
    for (int i = 0; i < num_inputs; ++i)
        if (inputs[i].connected && (inputs[i].channels < 0 || inputs[i].samples < 0 || (inputs[i].samples > 0 && inputs[i].channels > 0 && !inputs[i].data))) {
            h.lastError = "input " + std::to_string(i) + " is malformed";
            return EWH_HOST_ERROR;
        }

    ++h.cookCount;
    h.node.cookCount = static_cast<uint32_t>(h.cookCount);
    HostInputs in(h, inputs, num_inputs, default_rate, start_index, tops, parTops);
    in.setTotalCooks(h.cookCount);
    CHOP_CPlusPlusBase* op = h.instance;

    // pulses pressed since the last cook
    std::vector<std::string> pulses;
    pulses.swap(h.pulses);
    for (const std::string& name : pulses)
        if (!guarded(h, "pulsePressed", [&] { op->pulsePressed(name.c_str(), nullptr); })) return EWH_OPERATOR_FAULT;

    CHOP_GeneralInfo general{};
    if (!guarded(h, "getGeneralInfo", [&] { op->getGeneralInfo(&general, &in, nullptr); })) return EWH_OPERATOR_FAULT;
    r.timeslice = general.timeslice;
    r.matchIndex = general.inputMatchIndex;

    // what the CHOP would output if getOutputInfo returned false: the shape of the input it matches
    const OP_CHOPInput* match = in.chop(general.inputMatchIndex);
    CHOP_OutputInfo oinfo{};
    oinfo.numChannels = match ? match->numChannels : 1;
    oinfo.numSamples = match ? match->numSamples : 1;
    oinfo.startIndex = match ? static_cast<uint32_t>(match->startIndex) : static_cast<uint32_t>(start_index);
    oinfo.sampleRate = static_cast<float>(match ? match->sampleRate : default_rate);
    bool declared = false;
    if (!guarded(h, "getOutputInfo", [&] { declared = op->getOutputInfo(&oinfo, &in, nullptr); })) return EWH_OPERATOR_FAULT;
    r.declared = declared;

    if (!declared && !match) {
        h.hostError("getOutputInfo returned false but input " + std::to_string(general.inputMatchIndex) + " (inputMatchIndex) is not connected");
        h.lastError = h.hostErrors.back();
        return EWH_HOST_ERROR;
    }
    int nc = oinfo.numChannels, ns = oinfo.numSamples;
    double rate = oinfo.sampleRate;
    double start = oinfo.startIndex;
    if (general.timeslice) {
        // the length of a timeslice is dictated by TouchDesigner (frames elapsed x rate / fps); here by the caller
        const OP_CHOPInput* first = in.chop(0);
        ns = timeslice_samples > 0 ? timeslice_samples : (first ? first->numSamples : 1);
        start = start_index;
    }
    if (nc < 1 || ns < 1 || static_cast<double>(nc) * ns > 2e8) {
        h.hostError("the operator declared an output of " + std::to_string(nc) + " channels x " + std::to_string(ns) +
                    " samples, which the host does not accept");
        h.lastError = h.hostErrors.back();
        return EWH_HOST_ERROR;
    }

    // channel names
    std::vector<std::string> names(nc);
    for (int i = 0; i < nc; ++i) names[i] = "chan" + std::to_string(i + 1);
    if (declared) {
        for (int i = 0; i < nc; ++i) {
            HostString s;
            s.text = names[i];
            if (!guarded(h, "getChannelName", [&] { op->getChannelName(i, &s, &in, nullptr); })) return EWH_OPERATOR_FAULT;
            names[i] = s.text;
        }
    } else {
        for (int i = 0; i < nc && i < match->numChannels; ++i) names[i] = in.names(general.inputMatchIndex)[i];
    }

    // output buffers
    std::vector<float> storage(static_cast<size_t>(nc) * ns, fill);
    std::vector<float*> channels(nc);
    std::vector<const char*> namePointers(nc);
    for (int c = 0; c < nc; ++c) {
        channels[c] = storage.data() + static_cast<size_t>(c) * ns;
        namePointers[c] = names[c].c_str();
    }
    CHOP_Output out(nc, ns, static_cast<float>(rate), static_cast<uint32_t>(start), channels.data(), namePointers.data());
    r.numChannels = nc;
    r.numSamples = ns;
    r.sampleRate = rate;
    r.startIndex = start;
    r.names = names;

    if (!guarded(h, "execute", [&] { op->execute(&out, &in, nullptr); })) return EWH_OPERATOR_FAULT;
    r.data = storage;

    // Info CHOP
    int numInfo = 0;
    if (!guarded(h, "getNumInfoCHOPChans", [&] { numInfo = op->getNumInfoCHOPChans(nullptr); })) return EWH_OPERATOR_FAULT;
    if (numInfo < 0 || numInfo > 100000) {
        h.hostError("getNumInfoCHOPChans returned " + std::to_string(numInfo));
        numInfo = 0;
    }
    for (int i = 0; i < numInfo; ++i) {
        HostString name;
        OP_InfoCHOPChan chan{};
        chan.name = &name;
        if (!guarded(h, "getInfoCHOPChan", [&] { op->getInfoCHOPChan(i, &chan, nullptr); })) return EWH_OPERATOR_FAULT;
        r.infoChop.emplace_back(name.text, chan.value);
    }

    // Info DAT
    OP_InfoDATSize size{};
    bool hasDat = false;
    if (!guarded(h, "getInfoDATSize", [&] { hasDat = op->getInfoDATSize(&size, nullptr); })) return EWH_OPERATOR_FAULT;
    if (hasDat) {
        if (size.rows < 0 || size.cols < 0 || static_cast<double>(size.rows) * size.cols > 1e6) {
            h.hostError("getInfoDATSize gave " + std::to_string(size.rows) + " x " + std::to_string(size.cols));
        } else {
            r.hasDat = true;
            r.datRows = size.rows;
            r.datCols = size.cols;
            r.datCells.assign(static_cast<size_t>(size.rows) * size.cols, "");
            const int lines = size.byColumn ? size.cols : size.rows;
            const int entries = size.byColumn ? size.rows : size.cols;
            for (int line = 0; line < lines; ++line) {
                std::vector<HostString> cells(entries);
                std::vector<OP_String*> pointers(entries);
                for (int e = 0; e < entries; ++e) pointers[e] = &cells[e];
                OP_InfoDATEntries dat{};
                dat.values = pointers.data();
                if (!guarded(h, "getInfoDATEntries", [&] { op->getInfoDATEntries(line, entries, &dat, nullptr); })) return EWH_OPERATOR_FAULT;
                for (int e = 0; e < entries; ++e) {
                    const int row = size.byColumn ? e : line, col = size.byColumn ? line : e;
                    r.datCells[static_cast<size_t>(row) * size.cols + col] = cells[e].text;
                }
            }
        }
    }

    // popup, warning, error
    HostString popup, warning, error;
    if (!guarded(h, "getInfoPopupString", [&] { op->getInfoPopupString(&popup, nullptr); })) return EWH_OPERATOR_FAULT;
    if (!guarded(h, "getWarningString", [&] { op->getWarningString(&warning, nullptr); })) return EWH_OPERATOR_FAULT;
    if (!guarded(h, "getErrorString", [&] { op->getErrorString(&error, nullptr); })) return EWH_OPERATOR_FAULT;
    r.popup = popup.text;
    r.warning = warning.text;
    r.error = error.text;

    if (!h.hostErrors.empty()) {
        h.lastError.clear();
        for (const std::string& m : h.hostErrors) h.lastError += (h.lastError.empty() ? "" : "; ") + m;
        return EWH_HOST_ERROR;
    }
    return EWH_OK;
}

EWH_API int ewh_result_info(EwHost* host, EwCookInfo* info) {
    const Result& r = host->res;
    info->num_channels = r.numChannels;
    info->num_samples = r.numSamples;
    info->sample_rate = r.sampleRate;
    info->start_index = r.startIndex;
    info->timeslice = r.timeslice;
    info->output_declared = r.declared;
    info->input_match_index = r.matchIndex;
    info->cook_count = host->cookCount;
    return 0;
}

EWH_API int ewh_result_data(EwHost* host, float* dst, int capacity) {
    const std::vector<float>& d = host->res.data;
    const int n = static_cast<int>(d.size()) < capacity ? static_cast<int>(d.size()) : capacity;
    if (n > 0) std::memcpy(dst, d.data(), static_cast<size_t>(n) * sizeof(float));
    return n;
}

EWH_API const char* ewh_result_name(EwHost* host, int channel) {
    const Result& r = host->res;
    return channel >= 0 && channel < static_cast<int>(r.names.size()) ? r.names[channel].c_str() : "";
}
EWH_API const char* ewh_result_warning(EwHost* host) { return host->res.warning.c_str(); }
EWH_API const char* ewh_result_error(EwHost* host) { return host->res.error.c_str(); }
EWH_API const char* ewh_result_popup(EwHost* host) { return host->res.popup.c_str(); }
EWH_API int ewh_info_chop_count(EwHost* host) { return static_cast<int>(host->res.infoChop.size()); }
EWH_API const char* ewh_info_chop_name(EwHost* host, int i) {
    const auto& v = host->res.infoChop;
    return i >= 0 && i < static_cast<int>(v.size()) ? v[i].first.c_str() : "";
}
EWH_API float ewh_info_chop_value(EwHost* host, int i) {
    const auto& v = host->res.infoChop;
    return i >= 0 && i < static_cast<int>(v.size()) ? v[i].second : 0.f;
}
EWH_API int ewh_info_dat_size(EwHost* host, int* rows, int* cols) {
    *rows = host->res.datRows;
    *cols = host->res.datCols;
    return host->res.hasDat ? 1 : 0;
}
EWH_API const char* ewh_info_dat_cell(EwHost* host, int row, int col) {
    const Result& r = host->res;
    if (row < 0 || col < 0 || row >= r.datRows || col >= r.datCols) return "";
    return r.datCells[static_cast<size_t>(row) * r.datCols + col].c_str();
}

}  // extern "C"

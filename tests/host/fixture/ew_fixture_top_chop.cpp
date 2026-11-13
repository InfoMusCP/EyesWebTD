// A CHOP plugin that exists only to test the TOP inputs of the mock host (ew_td_host): it downloads the TOP on input 0
// with the pixel format and the vertical flip asked by its parameters and outputs the pixel values it received as one
// channel (fixed point formats as integers, float formats as they are), and reports what it saw in its Info DAT. The TOP is
// the wired input 0 when there is one, otherwise the TOP of the parameter Top (getParTOP).
// Like ew_fixture_chop.cpp it does not use the ew_td base layer.
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include "CHOP_CPlusPlusBase.h"

using namespace TD;

namespace {

struct Format {
    const char* name;
    const char* label;
    OP_PixelFormat format;  // Invalid: the native format of the texture
    int channels;           // 0: that of the native format
};

const Format kFormats[] = {
    {"native", "Native", OP_PixelFormat::Invalid, 0},
    {"mono8", "Mono8Fixed", OP_PixelFormat::Mono8Fixed, 1},
    {"rg8", "RG8Fixed", OP_PixelFormat::RG8Fixed, 2},
    {"rgba8", "RGBA8Fixed", OP_PixelFormat::RGBA8Fixed, 4},
    {"bgra8", "BGRA8Fixed", OP_PixelFormat::BGRA8Fixed, 4},
    {"mono16", "Mono16Fixed", OP_PixelFormat::Mono16Fixed, 1},
    {"rg16", "RG16Fixed", OP_PixelFormat::RG16Fixed, 2},
    {"rgba16", "RGBA16Fixed", OP_PixelFormat::RGBA16Fixed, 4},
    {"mono32f", "Mono32Float", OP_PixelFormat::Mono32Float, 1},
    {"rg32f", "RG32Float", OP_PixelFormat::RG32Float, 2},
    {"rgba32f", "RGBA32Float", OP_PixelFormat::RGBA32Float, 4},
    {"a8", "A8Fixed (not implemented by the host)", OP_PixelFormat::A8Fixed, 1},
};
constexpr int kFormatCount = sizeof(kFormats) / sizeof(kFormats[0]);

int nativeChannels(OP_PixelFormat f) {
    switch (f) {
        case OP_PixelFormat::Mono8Fixed: case OP_PixelFormat::Mono16Fixed: case OP_PixelFormat::Mono32Float: return 1;
        case OP_PixelFormat::RG8Fixed: case OP_PixelFormat::RG16Fixed: case OP_PixelFormat::RG32Float: return 2;
        default: return 4;
    }
}

int bytesPerChannel(OP_PixelFormat f) {
    switch (f) {
        case OP_PixelFormat::Mono16Fixed: case OP_PixelFormat::RG16Fixed: case OP_PixelFormat::RGBA16Fixed: return 2;
        case OP_PixelFormat::Mono32Float: case OP_PixelFormat::RG32Float: case OP_PixelFormat::RGBA32Float: return 4;
        default: return 1;
    }
}

}  // namespace

class FixtureTopCHOP : public CHOP_CPlusPlusBase {
public:
    explicit FixtureTopCHOP(const OP_NodeInfo*) {}

    void getGeneralInfo(CHOP_GeneralInfo* info, const OP_Inputs*, void*) override { info->timeslice = false; }

    bool getOutputInfo(CHOP_OutputInfo* info, const OP_Inputs* in, void*) override {
        info->numChannels = 1;
        info->numSamples = 1;
        info->sampleRate = 60.f;
        const OP_TOPInput* top = source(in);
        if (top) {
            const Format& f = kFormats[format(in)];
            const int channels = f.format == OP_PixelFormat::Invalid ? nativeChannels(top->textureDesc.pixelFormat) : f.channels;
            info->numSamples = static_cast<int>(top->textureDesc.width * top->textureDesc.height) * channels;
        }
        return true;
    }

    void getChannelName(int32_t, OP_String* name, const OP_Inputs*, void*) override { name->setString("pixels"); }

    void execute(CHOP_Output* out, const OP_Inputs* in, void*) override {
        ++cooks_;
        for (int s = 0; s < out->numSamples; ++s) out->channels[0][s] = -1.f;
        inputs_ = in->getNumInputs();
        chop0Null_ = in->getInputCHOP(0) == nullptr;
        const OP_TOPInput* top = source(in);
        topNull_ = top == nullptr;
        fromParameter_ = in->getNumInputs() == 0 || in->getInputTOP(0) == nullptr;
        resultNull_ = true;
        if (!top) return;
        width_ = top->textureDesc.width;
        height_ = top->textureDesc.height;
        nativeFormat_ = static_cast<int>(top->textureDesc.pixelFormat);
        path_ = top->opPath;
        opId_ = top->opId;
        totalCooks_ = top->totalCooks;

        OP_TOPInputDownloadOptions opts;
        opts.verticalFlip = in->getParInt("Flip") != 0;
        opts.pixelFormat = kFormats[format(in)].format;
        OP_SmartRef<OP_TOPDownloadResult> result = top->downloadTexture(opts, nullptr);
        if (!result) return;
        resultNull_ = false;
        gotFormat_ = static_cast<int>(result->textureDesc.pixelFormat);
        size_ = result->size;
        const OP_PixelFormat f = result->textureDesc.pixelFormat;
        const int bytes = bytesPerChannel(f);
        const unsigned char* data = static_cast<const unsigned char*>(result->getData());
        for (int s = 0; s < out->numSamples && static_cast<uint64_t>(s + 1) * bytes <= size_; ++s) {
            float v = 0.f;
            if (bytes == 1) v = data[s];
            else if (bytes == 2) { uint16_t u; std::memcpy(&u, data + 2 * s, 2); v = u; }
            else std::memcpy(&v, data + 4 * s, 4);
            out->channels[0][s] = v;
        }
    }

    int32_t getNumInfoCHOPChans(void*) override { return 0; }
    void getInfoCHOPChan(int32_t, OP_InfoCHOPChan*, void*) override {}

    bool getInfoDATSize(OP_InfoDATSize* size, void*) override {
        size->rows = 13;
        size->cols = 2;
        size->byColumn = false;
        return true;
    }
    void getInfoDATEntries(int32_t index, int32_t, OP_InfoDATEntries* entries, void*) override {
        const std::string rows[13][2] = {{"cooks", std::to_string(cooks_)},
                                         {"inputs", std::to_string(inputs_)},
                                         {"chop0_null", chop0Null_ ? "1" : "0"},
                                         {"top_null", topNull_ ? "1" : "0"},
                                         {"result_null", resultNull_ ? "1" : "0"},
                                         {"width", std::to_string(width_)},
                                         {"height", std::to_string(height_)},
                                         {"native_format", std::to_string(nativeFormat_)},
                                         {"format", std::to_string(gotFormat_)},
                                         {"size", std::to_string(size_)},
                                         {"path", path_},
                                         {"from_parameter", fromParameter_ ? "1" : "0"},
                                         {"op_id_total_cooks", std::to_string(opId_) + "," + std::to_string(totalCooks_)}};
        entries->values[0]->setString(rows[index][0].c_str());
        entries->values[1]->setString(rows[index][1].c_str());
    }

    void setupParameters(OP_ParameterManager* m, void*) override {
        OP_StringParameter fmt("Format");
        fmt.label = "Format";
        fmt.defaultValue = "native";
        const char* names[kFormatCount];
        const char* labels[kFormatCount];
        for (int i = 0; i < kFormatCount; ++i) names[i] = kFormats[i].name, labels[i] = kFormats[i].label;
        m->appendMenu(fmt, kFormatCount, names, labels);

        OP_StringParameter topPar("Top");
        topPar.label = "TOP";
        m->appendTOP(topPar);

        OP_NumericParameter flip("Flip");
        flip.label = "Vertical flip";
        m->appendToggle(flip);
    }

private:
    static const OP_TOPInput* source(const OP_Inputs* in) {
        const OP_TOPInput* top = in->getNumInputs() ? in->getInputTOP(0) : nullptr;
        return top ? top : in->getParTOP("Top");
    }
    static int format(const OP_Inputs* in) {
        const int i = in->getParInt("Format");
        return i >= 0 && i < kFormatCount ? i : 0;
    }

    int cooks_ = 0, inputs_ = 0, nativeFormat_ = -1, gotFormat_ = -1;
    bool chop0Null_ = true, topNull_ = true, resultNull_ = true, fromParameter_ = false;
    uint32_t width_ = 0, height_ = 0, opId_ = 0;
    uint64_t size_ = 0;
    int64_t totalCooks_ = 0;
    std::string path_;
};

extern "C" {
DLLEXPORT void FillCHOPPluginInfo(CHOP_PluginInfo* info) {
    if (!info->setAPIVersion(CHOPCPlusPlusAPIVersion)) return;
    info->customOPInfo.opType->setString("Ewfixturetop");
    info->customOPInfo.opLabel->setString("EW Host Fixture TOP");
    info->customOPInfo.authorName->setString("EyesWebTD tests");
    info->customOPInfo.authorEmail->setString("tests@example.invalid");
    info->customOPInfo.minInputs = 0;
    info->customOPInfo.maxInputs = 2;
}
DLLEXPORT CHOP_CPlusPlusBase* CreateCHOPInstance(const OP_NodeInfo* info) { return new FixtureTopCHOP(info); }
DLLEXPORT void DestroyCHOPInstance(CHOP_CPlusPlusBase* instance) { delete static_cast<FixtureTopCHOP*>(instance); }
}

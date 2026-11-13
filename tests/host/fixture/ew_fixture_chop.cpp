// A CHOP plugin that exists only to test the mock host (ew_td_host): it declares one parameter of every kind, can
// misbehave on request (Mode menu) and reports what it saw. It does not use the ew_td base layer, so that it tests the
// host against the raw TouchDesigner contract.
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>
#include "CHOP_CPlusPlusBase.h"

using namespace TD;

class FixtureCHOP : public CHOP_CPlusPlusBase {
public:
    explicit FixtureCHOP(const OP_NodeInfo* info) : nodeId_(info->opId), path_(info->opPath) {}

    void getGeneralInfo(CHOP_GeneralInfo* info, const OP_Inputs* in, void*) override {
        if (is(in, "timeslice")) info->timeslice = true;
        info->inputMatchIndex = in->getParInt("Match");
    }

    bool getOutputInfo(CHOP_OutputInfo* info, const OP_Inputs* in, void*) override {
        if (is(in, "match_input")) return false;
        info->numChannels = in->getParInt("Count");
        const OP_CHOPInput* first = in->getNumInputs() ? in->getInputCHOP(0) : nullptr;
        info->sampleRate = static_cast<float>(first ? first->sampleRate : 60.0);
        info->numSamples = first ? first->numSamples : 1;
        if (is(in, "fixed_clip")) info->numSamples = 5, info->startIndex = 7;
        if (is(in, "empty_output")) info->numChannels = 0;
        return true;
    }

    void getChannelName(int32_t index, OP_String* name, const OP_Inputs*, void*) override {
        name->setString(("out_" + std::to_string(index)).c_str());
    }

    void execute(CHOP_Output* out, const OP_Inputs* in, void*) override {
        ++cooks_;
        lastInputs_ = in->getNumInputs();
        lastNames_.clear();
        const OP_CHOPInput* input0 = in->getNumInputs() ? in->getInputCHOP(0) : nullptr;
        if (input0)
            for (int c = 0; c < input0->numChannels; ++c) {
                if (c) lastNames_ += ",";
                lastNames_ += input0->getChannelName(c);
            }
        lastStart_ = input0 ? input0->startIndex : -1;
        lastOutStart_ = out->startIndex;
        lastSamples_ = out->numSamples;
        gain_ = in->getParDouble("Gain");
        count_ = in->getParInt("Count");
        flag_ = in->getParInt("Flag");
        text_ = in->getParString("Text");
        mode_ = in->getParString("Mode");
        modeIndex_ = in->getParInt("Mode");
        floatAsInt_ = in->getParInt("Gain");
        double x = 0, y = 0, z = 0;
        in->getParDouble3("Offset", x, y, z);
        offset_ = x + 10 * y + 100 * z;
        in->enablePar("Text", flag_ != 0);
        timeInfo_ = in->getTimeInfo()->rate;

        if (is(in, "crash_access")) *static_cast<volatile int*>(nullptr) = 1;
        if (is(in, "crash_read")) cooks_ += *static_cast<volatile int*>(nullptr);
        if (is(in, "throw")) throw std::runtime_error("fixture exception");
        if (is(in, "terminate")) neverThrows();
        if (is(in, "abort")) std::abort();
        if (is(in, "bad_par")) (void)in->getParInt("Nope");
        if (is(in, "unsupported")) (void)in->getParDAT("Text");
        if (is(in, "divide_zero")) cooks_ = 10 / zeroDivisor();

        const OP_CHOPInput* first = in->getNumInputs() ? in->getInputCHOP(0) : nullptr;
        for (int c = 0; c < out->numChannels; ++c)
            for (int s = 0; s < out->numSamples; ++s) {
                double v = c;
                if (is(in, "timeslice")) v = static_cast<double>(out->startIndex) + s;  // the sample index
                else if (first && c < first->numChannels && s < first->numSamples) v = first->getChannelData(c)[s] * gain_ + c;
                if (!is(in, "leave_unwritten")) out->channels[c][s] = static_cast<float>(v + offset_);
            }
    }

    int32_t getNumInfoCHOPChans(void*) override { return 5; }
    void getInfoCHOPChan(int32_t index, OP_InfoCHOPChan* chan, void*) override {
        static const char* names[] = {"cooks", "pokes", "inputs", "gain", "start"};
        const double values[] = {static_cast<double>(cooks_), static_cast<double>(pokes_), static_cast<double>(lastInputs_), gain_, lastStart_};
        chan->name->setString(names[index]);
        chan->value = static_cast<float>(values[index]);
    }

    bool getInfoDATSize(OP_InfoDATSize* size, void*) override {
        size->rows = 8;
        size->cols = 2;
        size->byColumn = false;
        return true;
    }
    void getInfoDATEntries(int32_t index, int32_t, OP_InfoDATEntries* entries, void*) override {
        const std::string rows[8][2] = {{"mode", mode_},
                                        {"mode_index", std::to_string(modeIndex_)},
                                        {"text", text_},
                                        {"input_names", lastNames_},
                                        {"float_as_int", std::to_string(floatAsInt_)},
                                        {"out_start", std::to_string(lastOutStart_)},
                                        {"samples", std::to_string(lastSamples_)},
                                        {"rate", std::to_string(timeInfo_)}};
        entries->values[0]->setString(rows[index][0].c_str());
        entries->values[1]->setString(rows[index][1].c_str());
    }

    void getWarningString(OP_String* warning, void*) override {
        if (flag_ && mode_ != "error_string") warning->setString("flag is on");
    }
    void getErrorString(OP_String* error, void*) override {
        if (mode_ == "error_string") error->setString("fixture error");
    }
    void getInfoPopupString(OP_String* info, void*) override { info->setString(("node " + path_).c_str()); }

    void setupParameters(OP_ParameterManager* m, void*) override {
        OP_NumericParameter gain("Gain");
        gain.label = "Gain";
        gain.page = "Fixture";
        gain.defaultValues[0] = 1.0;
        gain.minValues[0] = 0.0;
        gain.maxValues[0] = 10.0;
        gain.clampMins[0] = gain.clampMaxes[0] = true;
        m->appendFloat(gain);

        OP_NumericParameter count("Count");
        count.label = "Count";
        count.page = "Fixture";
        count.defaultValues[0] = 2;
        count.minValues[0] = 1;
        count.maxValues[0] = 8;
        count.clampMins[0] = count.clampMaxes[0] = true;
        m->appendInt(count);

        OP_NumericParameter match("Match");
        match.label = "Match input";
        match.defaultValues[0] = 0;
        match.minValues[0] = 0;
        match.maxValues[0] = 3;
        match.clampMins[0] = match.clampMaxes[0] = true;
        m->appendInt(match);

        OP_NumericParameter flag("Flag");
        flag.label = "Flag";
        flag.page = "Fixture";
        m->appendToggle(flag);

        OP_NumericParameter offset("Offset");
        offset.label = "Offset";
        offset.page = "Fixture";
        m->appendXYZ(offset);

        OP_NumericParameter poke("Poke");
        poke.label = "Poke";
        poke.page = "Fixture";
        m->appendPulse(poke);

        OP_StringParameter text("Text");
        text.label = "Text";
        text.page = "Fixture";
        text.defaultValue = "hello";
        m->appendString(text);

        OP_StringParameter mode("Mode");
        mode.label = "Mode";
        mode.page = "Fixture";
        mode.defaultValue = "normal";
        const char* names[] = {"normal", "timeslice", "match_input", "fixed_clip", "empty_output", "leave_unwritten", "error_string",
                               "crash_access", "crash_read", "throw", "terminate", "abort", "bad_par", "unsupported", "divide_zero"};
        const char* labels[] = {"Normal", "Timeslice", "Match input", "Fixed clip", "Empty output", "Leave unwritten", "Error string",
                                "Crash (write)", "Crash (read)", "Throw", "Terminate", "Abort", "Bad parameter", "Unsupported call", "Divide by zero"};
        m->appendMenu(mode, 15, names, labels);

        // declarations the host must flag
        OP_NumericParameter odd("OddName");
        m->appendFloat(odd);
        OP_NumericParameter spaced("bad name");
        m->appendFloat(spaced);
        m->appendFloat(gain);
    }

    void pulsePressed(const char* name, void*) override {
        if (std::strcmp(name, "Poke") == 0) ++pokes_;
    }

private:
    bool is(const OP_Inputs* in, const char* mode) const { return std::strcmp(in->getParString("Mode"), mode) == 0; }
    static void neverThrows() noexcept { throw std::runtime_error("noexcept violated"); }
    static int zeroDivisor() {
        static volatile int zero = 0;
        return zero;
    }

    uint32_t nodeId_;
    std::string path_;
    int cooks_ = 0, pokes_ = 0, lastInputs_ = 0, lastSamples_ = 0, count_ = 0, flag_ = 0, modeIndex_ = 0, floatAsInt_ = 0;
    double lastStart_ = 0, gain_ = 0, offset_ = 0, timeInfo_ = 0;
    uint32_t lastOutStart_ = 0;
    std::string lastNames_, text_, mode_;
};

extern "C" {
DLLEXPORT void FillCHOPPluginInfo(CHOP_PluginInfo* info) {
    if (!info->setAPIVersion(CHOPCPlusPlusAPIVersion)) return;
    info->customOPInfo.opType->setString("Ewfixture");
    info->customOPInfo.opLabel->setString("EW Host Fixture");
    info->customOPInfo.authorName->setString("EyesWebTD tests");
    info->customOPInfo.authorEmail->setString("tests@example.invalid");
    info->customOPInfo.minInputs = 0;
    info->customOPInfo.maxInputs = 2;
}
DLLEXPORT CHOP_CPlusPlusBase* CreateCHOPInstance(const OP_NodeInfo* info) { return new FixtureCHOP(info); }
DLLEXPORT void DestroyCHOPInstance(CHOP_CPlusPlusBase* instance) { delete static_cast<FixtureCHOP*>(instance); }
}

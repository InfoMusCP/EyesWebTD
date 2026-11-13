// Base class of every EyesWeb CHOP. An operator declares WHAT it is (schema, sample count, parameters) and HOW it
// computes (cook); the base class does the rest of the TouchDesigner contract:
//   * channel count and names come from the schema, evaluated once per cook, not rebuilt for each channel;
//   * the outputs are zeroed before the cook, so a cook that stops early leaves zeros, never stale values;
//   * an exception of the cook (InputError from `require`, or anything the core throws) never leaves the plugin: it
//     becomes Status::InvalidInput with the message as reason, shown as the warning of the operator;
//   * the status of the last cook and its reason are shown on the Info CHOP and Info DAT, with the shape of the output
//     and what an operator adds in `describe`.
// Operators must not keep TouchDesigner pointers between cooks.
#pragma once
#include <exception>
#include <string>
#include <utility>
#include <vector>
#include "CPlusPlus_Common.h"
#include "CHOP_CPlusPlusBase.h"
#include "ew_td/info.h"
#include "ew_td/input.h"
#include "ew_td/params.h"
#include "ew_td/schema.h"
#include "ew_td/status.h"

namespace ew_td {

class EwChop : public TD::CHOP_CPlusPlusBase {
public:
    // ---- what an operator provides -------------------------------------------------------------------------------

    // Outputs of the operator; evaluated at the start of every cook, so it may depend on parameters and on the input.
    virtual Schema schema(const TD::OP_Inputs* in) const = 0;
    // Samples per output channel; default 1.
    virtual int numSamples(const TD::OP_Inputs*) const { return 1; }
    // Sample rate of the output; default the rate of input 0.
    virtual double sampleRate(const TD::OP_Inputs* in) const { return inputSampleRate(in); }
    // Parameters, declared once.
    virtual void declareParameters(Params&) {}
    // The computation. Write out->channels[c][s]; the channels follow the schema. Throw (`require`) for a bad input.
    virtual void cook(TD::CHOP_Output* out, const TD::OP_Inputs* in) = 0;
    // False for an operator that works without any input.
    virtual bool needsInput() const { return true; }
    // Entries an operator adds to its Info CHOP / DAT, after the common ones (status, reason, channels, samples, rate).
    virtual void describe(Info&) const {}

    // ---- state of the last cook ------------------------------------------------------------------------------------
    Status status() const { return status_; }
    const std::string& reason() const { return reason_; }

    // ---- TouchDesigner contract (operators do not override these) ------------------------------------------------
    void getGeneralInfo(TD::CHOP_GeneralInfo* info, const TD::OP_Inputs*, void*) override {
        info->cookEveryFrameIfAsked = false;
        info->timeslice = false;
        info->inputMatchIndex = 0;
    }

    bool getOutputInfo(TD::CHOP_OutputInfo* info, const TD::OP_Inputs* in, void*) override {
        names_ = schema(in).flatNames();
        info->numChannels = static_cast<int32_t>(names_.size());
        info->numSamples = numSamples(in);
        info->sampleRate = sampleRate(in);
        return true;
    }

    void getChannelName(int32_t index, TD::OP_String* name, const TD::OP_Inputs* in, void*) override {
        if (names_.empty()) names_ = schema(in).flatNames();
        if (index >= 0 && index < static_cast<int32_t>(names_.size())) name->setString(names_[index].c_str());
    }

    void execute(TD::CHOP_Output* out, const TD::OP_Inputs* in, void*) override {
        setStatus(Status::Ok, "");
        zero(out);
        if (needsInput() && in->getNumInputs() == 0) {
            setStatus(Status::NoOutput, "no input");
            finishCook(out);
            return;
        }
        try {
            cook(out, in);
        } catch (const std::exception& e) {
            setStatus(Status::InvalidInput, e.what());
            zero(out);
        } catch (...) {
            setStatus(Status::InvalidInput, "unknown error");
            zero(out);
        }
        finishCook(out);
    }

    int32_t getNumInfoCHOPChans(void*) override { return info_.numericCount(); }

    void getInfoCHOPChan(int32_t index, TD::OP_InfoCHOPChan* chan, void*) override {
        const InfoEntry& entry = info_.numericAt(index);
        chan->name->setString(entry.name.c_str());
        chan->value = static_cast<float>(entry.value);
    }

    bool getInfoDATSize(TD::OP_InfoDATSize* size, void*) override {
        size->rows = static_cast<int32_t>(info_.entries().size());
        size->cols = 2;
        size->byColumn = false;
        return true;
    }

    void getInfoDATEntries(int32_t index, int32_t, TD::OP_InfoDATEntries* entries, void*) override {
        const InfoEntry& entry = info_.entries()[index];
        entries->values[0]->setString(entry.name.c_str());
        entries->values[1]->setString(entry.text.c_str());
    }

    void getWarningString(TD::OP_String* warning, void*) override {
        if (status_ == Status::InvalidInput) warning->setString(reason_.c_str());
    }

    void setupParameters(TD::OP_ParameterManager* manager, void*) override {
        Params params(manager);
        declareParameters(params);
        declareCommonParameters(params);
    }

protected:
    // The state of a cook that has too few samples to produce a value yet: status WARMING_UP, "k of N samples" as in
    // PyEyesWeb. The operator then returns, leaving its outputs at zero.
    void warmingUp(int have, int need) {
        setStatus(Status::WarmingUp, std::to_string(have) + " of " + std::to_string(need) + " samples");
    }
    // For a sample-wise operator: true when sample `s` of `input` is not data (NaN or infinity). The cook then reports
    // INVALID_INPUT, leaves the output of that sample at zero and must not feed the sample to its feature, as PyEyesWeb
    // does not.
    bool skipNonFinite(const InputView& input, int s) {
        if (input.finite(s)) return false;
        setStatus(Status::InvalidInput, "NaN or infinity in the input");
        return true;
    }

    // Parameters that a family of operators shares, declared after those of the operator (see EwStreamChop).
    virtual void declareCommonParameters(Params&) {}

    // For a cook that goes on after a problem it reports (a single bad sample): the status and its reason are shown,
    // the cook is not interrupted.
    void setStatus(Status status, std::string reason) {
        status_ = status;
        reason_ = std::move(reason);
    }

private:
    void finishCook(const TD::CHOP_Output* out) {
        info_.clear();
        info_.number("status", static_cast<int>(status_), statusName(status_));
        info_.text("reason", reason_);
        info_.number("channels", out->numChannels);
        info_.number("samples", out->numSamples);
        info_.number("sample_rate", out->sampleRate);
        describe(info_);
    }

    static void zero(TD::CHOP_Output* out) {
        for (int c = 0; c < out->numChannels; ++c)
            for (int s = 0; s < out->numSamples; ++s) out->channels[c][s] = 0.f;
    }

    Status status_ = Status::Ok;
    std::string reason_;
    std::vector<std::string> names_;
    Info info_;
};

}  // namespace ew_td

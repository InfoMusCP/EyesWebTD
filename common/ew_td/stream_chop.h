// Base class of an operator that keeps state from cook to cook (a feature of the core that is fed sample after sample).
// It adds to EwChop what a stateful operator needs to behave in TouchDesigner as PyEyesWeb does in Python:
//
//   Source = stream   the input is a live timeslice. Every sample reaches the operator once, the state stays between
//                     cooks, and the output is a timeslice of the same length. An input that is not a timeslice (its
//                     length differs from the slice) is reported as INVALID_INPUT with the advice to use Clip, never
//                     silently fed in pieces.
//   Source = clip     the input is a recording. The state starts afresh at every cook, so the output depends on the
//                     clip alone (PyEyesWeb `run(recording)`); the output is a clip as long as the input.
//
//   Reset (pulse)     forgets the state at the next cook.
//
// An operator can ask for a stream output of ONE sample (`oneSampleInStream()`): every sample of the input still reaches
// the feature, but the output is always 1 sample, the result for the newest input sample, whatever number of samples the
// live source gives in a frame (1 or 2). The output then does not flip between a slice and a series, and an input that is
// not a timeslice is accepted. Clip is unchanged (one output sample per input sample).
//
// The state is also forgotten when the input changes its number of channels or its sample rate. Parameters are the
// concern of the operator: FeatureSlot hands them to the core feature, which decides what a change of them resets.
//
// An operator implements `process` (feed the samples of the input to its feature, write the outputs) and `dropState`
// (forget its feature and anything else it keeps). `process` is not called after an error of the input is found.
#pragma once
#include <cstring>
#include <string>
#include "ew_td/chop_base.h"
#include "ew_td/stream_state.h"

namespace ew_td {

class EwStreamChop : public EwChop {
public:
    // Feed the samples of `input` to the feature and write the outputs: `out->numSamples` samples per channel (the
    // samples of the input in clip mode, the slice in stream mode; both equal input.samples()).
    virtual void process(TD::CHOP_Output* out, const TD::OP_Inputs* in, const InputView& input) = 0;
    // Forget the accumulated state. Called before `process` when the state must start afresh.
    virtual void dropState() = 0;

    int numSamples(const TD::OP_Inputs* in) const override { return singleSample(in) ? 1 : inputSamples(in); }

    void getGeneralInfo(TD::CHOP_GeneralInfo* info, const TD::OP_Inputs* in, void* reserved) override {
        EwChop::getGeneralInfo(info, in, reserved);
        info->timeslice = !isClip(in) && !oneSampleInStream();  // in clip mode, and for one sample, the length is the one of getOutputInfo
    }

    void pulsePressed(const char* name, void*) override {
        if (std::strcmp(name, "Reset") == 0) state_.requestReset();
    }

    void describe(Info& info) const override {
        info.text("state_reset", resetReasonName(state_.lastReason()));
        info.number("samples_processed", static_cast<double>(state_.samplesProcessed()));
        info.number("resets", state_.resets());
        describeStream(info);
    }

    void cook(TD::CHOP_Output* out, const TD::OP_Inputs* in) final {
        const InputView input = chopInput(in);
        const bool clip = isClip(in);
        if (!clip && !oneSampleInStream())
            require(input.samples() == out->numSamples,
                    "Input is not a timeslice (" + std::to_string(input.samples()) + " samples for a slice of " +
                        std::to_string(out->numSamples) + "); set Source to Clip to process a recording");
        if (state_.begin({input.channels(), input.sampleRate()}, clip) != ResetReason::None) dropState();
        process(out, in, input);
        state_.processed(input.samples());
    }

protected:
    // True for an operator whose stream output is one sample, the newest (see the top of the file). Default false.
    virtual bool oneSampleInStream() const { return false; }

    // True when this cook outputs one sample: Stream mode of an operator with oneSampleInStream().
    bool singleSample(const TD::OP_Inputs* in) const { return oneSampleInStream() && !isClip(in); }

    // Entries that a streaming operator adds to its Info output.
    virtual void describeStream(Info&) const {}

    void declareCommonParameters(Params& p) override {
        p.page("Cook");
        p.menu("Source", "Source", "stream",
               {{"stream", "Stream (live timeslice)"}, {"clip", "Clip (recording, fresh state each cook)"}});
        p.pulse("Reset", "Reset");
    }

private:
    static bool isClip(const TD::OP_Inputs* in) { return std::strcmp(in->getParString("Source"), "clip") == 0; }

    StreamState state_;
};

}  // namespace ew_td

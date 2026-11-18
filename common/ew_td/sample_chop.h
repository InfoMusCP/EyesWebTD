// Base of the sample-wise operators: every input sample is one frame (a point cloud, a pose, a point) and the output has
// one sample for each of them, with no state between samples (Bounding Box Filled Area, Ellipsoid Sphericity, ...).
//
// Source (a parameter of the page Cook):
//   Stream (default) a live input. The output is always ONE sample, the result for the newest input sample, whatever
//                    number of samples the live source gives in a frame (1 or 2): it never flips between a slice and a
//                    series, and an expression reading it always sees the newest value. The input need not be a timeslice.
//   Clip             the input is a recording: one output sample per input sample.
//
// An operator reads its input with `sampleInput(in)`, which in Stream holds only the newest sample.
#pragma once
#include <cstring>
#include <string>
#include "ew_td/chop_base.h"
#include "ew_td/input.h"

namespace ew_td {

class EwSampleChop : public EwChop {
public:
    int numSamples(const TD::OP_Inputs* in) const override { return singleSample(in) ? 1 : inputSamples(in); }

    void getGeneralInfo(TD::CHOP_GeneralInfo* info, const TD::OP_Inputs* in, void* reserved) override {
        EwChop::getGeneralInfo(info, in, reserved);
        // in clip mode, and for one sample, the length of the output is the one of getOutputInfo
        info->timeslice = !isClip(in) && !oneSampleInStream();
    }

protected:
    // True for an operator whose stream output is one sample, the newest (see the top of the file). Default true.
    virtual bool oneSampleInStream() const { return true; }

    // True when this cook outputs one sample: Stream mode of an operator with oneSampleInStream().
    bool singleSample(const TD::OP_Inputs* in) const { return oneSampleInStream() && !isClip(in); }

    // The index of the sample to read when the output is one sample: the newest of the input (-1 when it is empty).
    int newestSample(const TD::OP_Inputs* in) const { return inputSamples(in) - 1; }

    // The input to read: in Stream (one sample) only the newest sample, otherwise the whole input.
    InputView sampleInput(const TD::OP_Inputs* in) const {
        const InputView input = chopInput(in);
        return singleSample(in) && input.samples() > 0 ? input.from(input.samples() - 1) : input;
    }

    void declareCommonParameters(Params& p) override {
        p.page("Cook");
        p.menu("Source", "Source", "stream", {{"stream", "Stream (live timeslice)"}, {"clip", "Clip (recording)"}});
    }

    // To call at the start of cook(), `if (!checkSlice(out, in)) return;`: in stream mode the input must be the slice that
    // TouchDesigner asked for. Otherwise the status is INVALID_INPUT, with the reason, and the outputs stay as they are.
    bool checkSlice(const TD::CHOP_Output* out, const TD::OP_Inputs* in) {
        if (isClip(in) || oneSampleInStream()) return true;
        const int samples = inputSamples(in);
        if (samples == out->numSamples) return true;
        setStatus(Status::InvalidInput, "Input is not a timeslice (" + std::to_string(samples) + " samples for a slice of " +
                                            std::to_string(out->numSamples) + "); set Source to Clip to process a recording");
        return false;
    }

private:
    static bool isClip(const TD::OP_Inputs* in) { return std::strcmp(in->getParString("Source"), "clip") == 0; }
};

}  // namespace ew_td

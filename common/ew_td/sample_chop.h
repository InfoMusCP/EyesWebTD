// Base of the sample-wise operators: every input sample is one frame (a point cloud, a pose, a point) and the output has
// one sample for each of them, with no state between samples (Bounding Box Filled Area, Ellipsoid Sphericity, ...).
//
// Source (a parameter of the page Cook):
//   Stream (default) the input is a live timeslice. The output is declared as a timeslice too, so TouchDesigner decides its
//                    length at every cook (a live source may give 1 or 2 samples in a frame) and the viewer does not flip
//                    between a series and a slice. An input that is not a timeslice (its length differs from the slice) is
//                    INVALID_INPUT: set Source to Clip.
//   Clip             the input is a recording: the output has the length of the input.
#pragma once
#include <cstring>
#include <string>
#include "ew_td/chop_base.h"
#include "ew_td/input.h"

namespace ew_td {

class EwSampleChop : public EwChop {
public:
    int numSamples(const TD::OP_Inputs* in) const override { return inputSamples(in); }

    void getGeneralInfo(TD::CHOP_GeneralInfo* info, const TD::OP_Inputs* in, void* reserved) override {
        EwChop::getGeneralInfo(info, in, reserved);
        info->timeslice = !isClip(in);  // in clip mode the length of the output is the one of getOutputInfo
    }

protected:
    void declareCommonParameters(Params& p) override {
        p.page("Cook");
        p.menu("Source", "Source", "stream", {{"stream", "Stream (live timeslice)"}, {"clip", "Clip (recording)"}});
    }

    // To call at the start of cook(), `if (!checkSlice(out, in)) return;`: in stream mode the input must be the slice that
    // TouchDesigner asked for. Otherwise the status is INVALID_INPUT, with the reason, and the outputs stay as they are.
    bool checkSlice(const TD::CHOP_Output* out, const TD::OP_Inputs* in) {
        if (isClip(in)) return true;
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

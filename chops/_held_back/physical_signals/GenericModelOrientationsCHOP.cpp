// TouchDesigner Generic Model Orientations CHOP - wraps ew::humanoid::GenericModelOrientationsExtractor
// The bone vectors of a mass-spring model of your own from the positions of its masses: for every spring, the vector
// from its first mass to its second one (not normalised, in the unit of the data).
// The model is given as EyesWeb XML (parameters Modelxml / Modelfile), see generic_model_common.h, which also describes
// the channel order and the dropouts.
// Input:  3 channels per mass (x y z, joint-major), the masses in ascending order of their names; one frame per sample.
// Output: 3 channels per spring (directions_<spring>_x|y|z, the PyEyesWeb flat names), springs in ascending order of
//         their names, one output sample per input sample. A spring with a missing mass is NaN.
// Kind: frame operator without state (a sample is a frame); the sample rate of the input is kept.
// Statuses: INVALID_INPUT for a model that cannot be read, a wrong channel count, and per sample an infinite value or a
// frame without any finite value (that output sample is zero); OK otherwise (no warm-up).
#include <string>
#include <vector>
#include "ew/features/humanoid/generic_model_orientations_extractor.h"
#include "ew_td/plugin.h"
#include "generic_model_common.h"

using namespace TD;
using namespace ew_td;
using ew::humanoid::GenericModelOrientationsExtractor;

class GenericModelOrientationsCHOP : public EwChop {
public:
    explicit GenericModelOrientationsCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs* in) const override {
        return {gm::pointsOutput("directions", source_.peek(in), true)};
    }

    int numSamples(const OP_Inputs* in) const override { return inputSamples(in); }

    void declareParameters(Params& p) override { gm::declareModel(p); }

    void describe(Info& info) const override { info.text("input_names", inputNames_); }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        const ew::humanoid::MassSpringModel& model = source_.get(in);
        const std::vector<std::string> masses = gm::massNames(model);
        const std::vector<std::string> springs = gm::springNames(model);
        inputNames_ = gm::joined(masses);
        require(!springs.empty(), "the model has no springs");
        gm::requireChannels(input, masses.size(), "masses", masses);

        const GenericModelOrientationsExtractor extractor(model);
        for (int s = 0; s < out->numSamples; ++s) {
            const std::string problem = gm::frameProblem(input, s);
            if (!problem.empty()) {
                setStatus(Status::InvalidInput, problem);
                continue;
            }
            gm::writePoints(out, 0, s, extractor.process(gm::readNamedPoints(input, s, masses)), extractor.outputLabels());
        }
    }

private:
    gm::ModelSource source_;
    mutable std::string inputNames_;
};

EW_TD_CHOP(GenericModelOrientationsCHOP, "Ewgenericmodelorientations", "EW L1 Generic Model Orientations", 1, 1)

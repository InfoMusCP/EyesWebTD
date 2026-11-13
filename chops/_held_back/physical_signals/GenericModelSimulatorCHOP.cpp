// TouchDesigner Generic Model Simulator CHOP - wraps ew::humanoid::GenericModelSimulator
// A mass-spring model of your own that follows bone directions: the springs are pulled towards the directions of the
// input, the model is integrated in time and the positions of its masses come out (a smooth, always articulated
// movement). The model is given as EyesWeb XML (parameters Modelxml / Modelfile); see generic_model_common.h for the
// model, the channel order and the dropouts.
// Input:  3 channels per spring (x y z, joint-major), the springs in ascending order of their names, typically the
//         output of Generic Model Orientations; one frame per sample. A direction with a NaN is missing (its spring
//         keeps its direction).
// Output: 3 channels per mass (positions_<mass>_x|y|z, the PyEyesWeb flat names), masses in ascending order of their
//         names, one output sample per input sample, in the unit of the model. The time step of a sample is
//         1 / sample rate of the input (PyEyesWeb: sampling_rate); units is not a parameter (it only names the unit).
// Parameters: those of PyEyesWeb with its defaults (damping 10, integration step 0.001 s, forces, floor, gravity as three
//         numbers), Startfrominput (the first frame after a Reset puts the tips of the springs on the input).
// Kind: stream (EwStreamChop): the state (masses, velocities, rest directions) stays between cooks, Source = clip starts
//         afresh at every cook, Reset forgets. A change of the model restarts the state; all other parameters are live.
// Statuses: INVALID_INPUT for a model that cannot be read, a wrong channel count or an invalid parameter (the integration
//         step), and per sample an infinite value or a frame without any finite value (output zero, model not fed); OK
//         otherwise (no warm-up).
#include <string>
#include <vector>
#include "ew/features/humanoid/generic_model_simulator.h"
#include "ew_td/plugin.h"
#include "ew_td/stream_chop.h"
#include "generic_model_common.h"

using namespace TD;
using namespace ew_td;
using ew::humanoid::GenericModelSimulator;

class GenericModelSimulatorCHOP : public EwStreamChop {
public:
    explicit GenericModelSimulatorCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs* in) const override { return {gm::pointsOutput("positions", source_.peek(in), false)}; }

    void declareParameters(Params& p) override {
        gm::declareModel(p);
        gm::declareBase(p);
        p.page("Simulator");
        p.toggle("Startfrominput", "Start From Input", false);
    }

    void describeStream(Info& info) const override { info.text("input_names", inputNames_); }

    void process(CHOP_Output* out, const OP_Inputs* in, const InputView& input) override {
        const ew::humanoid::MassSpringModel& model = source_.get(in);
        if (generation_ != source_.generation()) {
            if (generation_ != 0) dropState();
            generation_ = source_.generation();
        }
        const std::vector<std::string> springs = gm::springNames(model);
        const std::vector<std::string> masses = gm::massNames(model);
        inputNames_ = gm::joined(springs);
        require(!springs.empty(), "the model has no springs");
        gm::requireChannels(input, springs.size(), "springs", springs);

        GenericModelSimulator::Params p;
        gm::readBase(in, p);
        GenericModelSimulator& feature = slot_.get(model, p);
        const bool startFromInput = in->getParInt("Startfrominput") != 0;

        for (int s = 0; s < out->numSamples; ++s) {
            const std::string problem = gm::frameProblem(input, s);
            if (!problem.empty()) {
                setStatus(Status::InvalidInput, problem);
                continue;
            }
            const bool teleport = startFromInput && fresh_;
            fresh_ = false;
            gm::writePoints(out, 0, s, feature.process(gm::readNamedPoints(input, s, springs), input.dt(), {}, teleport),
                            masses);
        }
    }

    void dropState() override {
        slot_.drop();
        fresh_ = true;
    }

private:
    gm::ModelSource source_;
    gm::ModelSlot<GenericModelSimulator> slot_;
    int generation_ = 0;
    bool fresh_ = true;
    mutable std::string inputNames_;
};

EW_TD_CHOP(GenericModelSimulatorCHOP, "Ewgenericmodelsimulator", "EW L1 Generic Model Simulator", 1, 1)

// TouchDesigner Kinetic Energy CHOP - wraps ew::motion::KineticEnergyIndex
// Input: N channels, layout joint-major (j0x j0y j0z j1x ...). Par "Dims" sets axes per joint.
// Input = velocity: the input holds velocities, one value per sample, no finite difference.
// Input = positions: the input holds positions (Dims = 3); the finite difference runs across cooks (dt = 1/sampleRate).
// Weight is the same for every joint in both modes (labels "0", "1", ...).
// Output: 1 channel (kinetic_energy), one sample per input sample.
// Streaming operator (see ew_td/stream_chop.h): Source = stream keeps the previous frame between cooks, Source = clip
// starts afresh at every cook; Reset forgets the state.
#include <sstream>
#include <algorithm>
#include <cstring>
#include "ew/features/motion/kinetic_energy_index.h"
#include "ew_td/plugin.h"
#include "ew_td/slot.h"
#include "ew_td/stream_chop.h"

using namespace TD;
using namespace ew_td;
using ew::motion::KineticEnergyIndex;

class KineticEnergyCHOP : public EwStreamChop {
public:
    explicit KineticEnergyCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::scalar("kinetic_energy")}; }

    void declareParameters(Params& p) override {
        p.page("Kinetic Energy");
        p.menu("Inputmode", "Input Mode", "velocity", {{"velocity", "Velocity (PyEyesWeb)"}, {"position", "Positions (EyesWeb)"}});
        p.integer("Dims", "Dims", 3, Range::between(1, 4));
        p.number("Weight", "Weight (mass)", 1.0, Range::atLeast(0, 10));
        p.string("Weights", "Weights per joint (e.g. 1 2 0.5; empty = Weight for all)", "");
        p.integer("Referencepoint", "Reference Joint (-1 = none, position mode)", -1, Range::atLeast(-1, 200));
    }

    void process(CHOP_Output* out, const OP_Inputs* in, const InputView& input) override {
        const bool positions = std::strcmp(in->getParString("Inputmode"), "position") == 0;
        const int dims = std::max(1, in->getParInt("Dims"));
        const int joints = jointCount(input, dims);
        if (positions) require(dims == 3, "Positions input requires Dims = 3");

        KineticEnergyIndex::Params p;
        p.inputMode = positions ? KineticEnergyIndex::InputMode::Position : KineticEnergyIndex::InputMode::Velocity;
        const double weight = in->getParDouble("Weight");
        for (int j = 0; j < joints; ++j) p.weights[labels_[j]] = weight;
        {   // one weight per joint, in the order of the joints; a joint without one keeps Weight (PyEyesWeb `weights`)
            std::stringstream list(in->getParString("Weights") ? in->getParString("Weights") : "");
            double value;
            for (int j = 0; j < joints && (list >> value); ++j) p.weights[labels_[j]] = value;
        }
        const int reference = in->getParInt("Referencepoint");
        if (reference >= 0) {
            require(positions, "Reference Joint needs the position input mode (a velocity has no origin)");
            require(reference < joints, "Reference Joint is not among the joints");
            p.referencePoint = labels_[reference];
        }
        KineticEnergyIndex& feature = feature_.get(p);

        const double dt = positions ? input.dt() : 1.0;
        for (int s = 0; s < out->numSamples; ++s) {
            if (skipNonFinite(input, s)) continue;
            out->channels[0][s] = static_cast<float>(feature.process(readFrame(input, dims, s, labels_), dt));
        }
    }

    void dropState() override { feature_.drop(); }

private:
    FeatureSlot<KineticEnergyIndex> feature_;
    JointLabels labels_;
};

EW_TD_CHOP(KineticEnergyCHOP, "Ewkineticenergy", "EW L2 Kinetic Energy", 1, 1)

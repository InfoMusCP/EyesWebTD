// TouchDesigner Equilibrium CHOP - wraps ew::motion::Equilibrium
// Input: 6 channels: left_foot_x, left_foot_y, right_foot_x, right_foot_y, barycenter_x, barycenter_y.
// Output: 2 channels: equilibrium (0..1), angle (degrees), one sample per input sample.
// Parameters: Margin, Yweight.
// A sample with coincident feet or NaN / infinity: INVALID_INPUT, its outputs stay 0.
#include "ew/features/motion/equilibrium.h"
#include "ew_td/plugin.h"
#include "ew_td/sample_chop.h"

using namespace TD;
using namespace ew_td;
using ew::motion::Equilibrium;

class EquilibriumCHOP : public EwSampleChop {
public:
    explicit EquilibriumCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::scalar("equilibrium"), Output::scalar("angle")}; }

    void declareParameters(Params& p) override {
        p.page("Equilibrium");
        p.number("Margin", "Margin", 0.1, Range::atLeast(0, 1));
        p.number("Yweight", "Y Weight", 0.5, Range::atLeast(0, 10));
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        if (!checkSlice(out, in)) return;
        const InputView input = sampleInput(in);
        require(input.channels() >= 6, "Equilibrium requires at least 6 channels: lf_x, lf_y, rf_x, rf_y, bary_x, bary_y");

        Equilibrium::Params p;
        p.margin = in->getParDouble("Margin");
        p.yWeight = in->getParDouble("Yweight");
        const Equilibrium feature(p);

        for (int s = 0; s < out->numSamples; ++s) {
            if (skipNonFinite(input, s)) continue;
            if (input.at(0, s) == input.at(2, s) && input.at(1, s) == input.at(3, s)) {
                setStatus(Status::InvalidInput, "the feet coincide: no support vector");
                continue;
            }
            const ew::Point2 leftFoot{input.at(0, s), input.at(1, s)};
            const ew::Point2 rightFoot{input.at(2, s), input.at(3, s)};
            const ew::Point2 barycenter{input.at(4, s), input.at(5, s)};
            const auto result = feature.process(leftFoot, rightFoot, barycenter);
            out->channels[0][s] = static_cast<float>(result.value);
            out->channels[1][s] = static_cast<float>(result.angleDeg);
        }
    }
};

EW_TD_CHOP(EquilibriumCHOP, "Ewequilibrium", "EW L2 Equilibrium", 1, 1)

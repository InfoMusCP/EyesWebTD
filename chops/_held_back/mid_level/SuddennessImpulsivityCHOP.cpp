// TouchDesigner Suddenness Impulsivity CHOP - wraps ew::motion::SuddennessImpulsivity (PyEyesWeb SuddennessImpulsivity)
// Impulsivity of a trajectory: its direction change (Epsilon) when it is also sudden (the Suddenness test on the speeds
// of the window), else 0. Both terms read the same trajectory.
// Input: one trajectory, Dims channels (2 or 3), like PyEyesWeb; for a skeleton, select the joint first. The whole input
// is one window, at least 6 samples.
// Output: 1 channel, 1 sample: impulsivity_index in [0, 1].
// Status: WARMING_UP below 6 samples; INVALID_INPUT for NaN or infinity and, with Algorithm = Quantile, a window the
// fit cannot handle (the output stays 0). Frame operator: nothing is kept between cooks.
#include <cstring>
#include <string>
#include "ew/common/matrix.h"
#include "ew/features/motion/impulsivity.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;
using ew::motion::Suddenness;
using ew::motion::SuddennessImpulsivity;

class SuddennessImpulsivityCHOP : public EwChop {
public:
    static constexpr int kMinRows = 6;

    explicit SuddennessImpulsivityCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::scalar("impulsivity_index")}; }

    void declareParameters(Params& p) override {
        p.page("Suddenness Impulsivity");
        p.menu("Algorithm", "Algorithm", "constrained",
               {{"constrained", "Constrained (EyesWeb)"}, {"quantile", "Quantile"}});
        p.integer("Dims", "Dims", 3, Range::between(2, 3));
        p.number("Epsilon", "Direction Change Epsilon", 0.5, Range::atLeast(0.0001, 1.0).withSlider(0.01, 1.0));
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        const int dims = in->getParInt("Dims");
        require(dims == 2 || dims == 3, "Dims must be 2 or 3");
        require(input.channels() == dims, "Input must be one trajectory: " + std::to_string(dims) + " channels (Dims), got " +
                                              std::to_string(input.channels()));
        const int rows = input.samples();
        if (rows < kMinRows) return warmingUp(rows, kMinRows);
        requireFinite(input);

        ew::Matrix trajectory(rows, dims);
        for (int t = 0; t < rows; ++t)
            for (int d = 0; d < dims; ++d) trajectory(t, d) = input.at(d, t);

        SuddennessImpulsivity::Params p;
        p.directionChangeEpsilon = in->getParDouble("Epsilon");
        p.algorithm = std::strcmp(in->getParString("Algorithm"), "quantile") == 0 ? Suddenness::Algorithm::Quantile
                                                                                 : Suddenness::Algorithm::Constrained;
        const auto result = SuddennessImpulsivity(p).process(trajectory);
        if (!result) return warmingUp(rows, kMinRows);
        if (result->alpha == -1) return setStatus(Status::InvalidInput, "the distribution could not be fitted");
        out->channels[0][0] = static_cast<float>(result->impulsivityIndex);
    }
};

EW_TD_CHOP(SuddennessImpulsivityCHOP, "Ewsuddennessimpulsivity", "EW L3 Suddenness Impulsivity", 1, 1)

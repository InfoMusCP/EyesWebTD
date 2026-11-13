// TouchDesigner Trajectory Non-Planarity CHOP - wraps ew::trajectory::TrajectoryNonPlanarity
// Measures the distance of local neighbourhoods along a 3D path from best-fit planes.
// Input: 3 channels (x, y, z) across N samples.
// Fewer than 2 points, NaN or infinity, no point with another point within the radius (nothing to fit), or more
// than NaN Fraction of undefined local planes: INVALID_INPUT.
// Output: 1 channel: curvature_radius, the mean distance from the local planes, in the unit of the input.
#include <cmath>
#include "ew/features/trajectory/trajectory_non_planarity.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;
using ew::trajectory::TrajectoryNonPlanarity;

class TrajectoryNonPlanarityCHOP : public EwChop {
public:
    explicit TrajectoryNonPlanarityCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs* in) const override {
        return {Output::scalar("curvature_radius")};
    }

    void declareParameters(Params& p) override {
        p.page("Non-Planarity");
        p.number("Radius", "Search Radius", 0.1, Range::atLeast(0.001, 500.0).withSlider(0.01, 2.0));
        p.number("Nanfraction", "NaN Fraction", 0.5, Range::between(0.0, 1.0));
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        require(input.channels() >= 3, "TrajectoryNonPlanarity requires 3 channels (x, y, z)");
        require(input.samples() >= 2, "fewer than 2 points");
        requireFinite(input);

        TrajectoryNonPlanarity::Params p;
        p.radius = in->getParDouble("Radius");
        p.nanFraction = in->getParDouble("Nanfraction");
        const TrajectoryNonPlanarity feature(p);

        const double value = feature.process(readTrajectory(input, false));
        require(std::isfinite(value), "no point has another point within radius, or too many undefined local planes: nothing to fit");
        out->channels[0][0] = static_cast<float>(value);
    }
};

EW_TD_CHOP(TrajectoryNonPlanarityCHOP, "Ewtrajectorynonplanarity", "EW L2 Trajectory Non-Planarity", 1, 1)

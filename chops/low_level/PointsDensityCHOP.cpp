// TouchDesigner Points Density CHOP - wraps ew::motion::PointsDensity
// Input: 3N channels, joint-major (j0_x, j0_y, j0_z, j1_x, ...); every sample is one point cloud.
// Output: centroid_x, centroid_y, centroid_z, then density (Distance Dimension = module) or density_x, density_y,
// density_z (component), one sample per input sample. A sample without points or with NaN / infinity leaves its
// outputs at 0 (the latter is INVALID_INPUT).
#include <cstring>
#include <string>
#include <vector>
#include "ew/features/motion/points_density.h"
#include "ew_td/plugin.h"
#include "ew_td/sample_chop.h"

using namespace TD;
using namespace ew_td;
using ew::motion::PointsDensity;

namespace {
bool perAxis(const OP_Inputs* in) { return std::strcmp(in->getParString("Outputdims"), "components") == 0; }
}  // namespace

class PointsDensityCHOP : public EwSampleChop {
public:
    explicit PointsDensityCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs* in) const override {
        const std::vector<std::string> xyz{"x", "y", "z"};
        return {Output::vector("centroid", xyz), perAxis(in) ? Output::vector("density", xyz) : Output::scalar("density")};
    }

    void declareParameters(Params& p) override {
        p.page("Points Density");
        p.menu("Centroidtype", "Centroid Type", "mean", {{"mean", "Mean"}, {"median", "Median"}});
        p.menu("Distancetype", "Distance Aggregator", "mean",
               {{"mean", "Mean"}, {"median", "Median"}, {"max", "Max"}, {"sum", "Sum"}});
        p.menu("Outputdims", "Output Dims", "module",
               {{"module", "Module (Scalar)"}, {"components", "Component (Point 3D)"}});
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        if (!checkSlice(out, in)) return;
        const InputView input = sampleInput(in);
        const int points = jointCount(input, 3);

        PointsDensity::Params p;
        p.parameterCentroidType = std::strcmp(in->getParString("Centroidtype"), "median") == 0
                                      ? PointsDensity::CentroidType::Median : PointsDensity::CentroidType::Mean;
        const char* distance = in->getParString("Distancetype");
        if (std::strcmp(distance, "median") == 0) p.parameterDistanceType = PointsDensity::DistanceType::Median;
        else if (std::strcmp(distance, "max") == 0) p.parameterDistanceType = PointsDensity::DistanceType::Max;
        else if (std::strcmp(distance, "sum") == 0) p.parameterDistanceType = PointsDensity::DistanceType::SumOfLengths;
        else p.parameterDistanceType = PointsDensity::DistanceType::Mean;
        const bool components = perAxis(in);
        p.parameterDistanceDim = components ? PointsDensity::DistanceDim::Component : PointsDensity::DistanceDim::Module;
        const PointsDensity feature(p);

        for (int s = 0; s < out->numSamples; ++s) {
            if (skipNonFinite(input, s)) continue;
            ew::LabelledSet3 cloud;
            for (int i = 0; i < points; ++i) cloud[labels_[i]] = readPoint(input, i, 3, s);
            const auto result = feature.process(cloud);
            if (!result) continue;
            out->channels[0][s] = static_cast<float>(result->centroid.x);
            out->channels[1][s] = static_cast<float>(result->centroid.y);
            out->channels[2][s] = static_cast<float>(result->centroid.z);
            if (components) {
                out->channels[3][s] = static_cast<float>(result->densityPoint.x);
                out->channels[4][s] = static_cast<float>(result->densityPoint.y);
                out->channels[5][s] = static_cast<float>(result->densityPoint.z);
            } else {
                out->channels[3][s] = static_cast<float>(result->density);
            }
        }
    }

private:
    JointLabels labels_;
};

EW_TD_CHOP(PointsDensityCHOP, "Ewpointsdensity", "EW L2 Points Density", 1, 1)

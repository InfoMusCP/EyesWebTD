// TouchDesigner Ellipsoid Sphericity CHOP - wraps ew::motion::EllipsoidSphericity
// Input Mode = sizes: input 3 channels (sizeX, sizeY, sizeZ). Output: sphericity (Wadell psi).
// Input Mode = points: input 3N channels (point cloud x, y, z per point). Output: sphericity, axis_ratio, radii_0
// (major), radii_1 (middle), radii_2 (minor). One sample per input sample.
// A sample with non-positive sizes, fewer than 2 points, no extent or NaN / infinity: INVALID_INPUT, its outputs stay 0.
#include <cmath>
#include <cstring>
#include <vector>
#include "ew/features/motion/ellipsoid_sphericity.h"
#include "ew_td/plugin.h"
#include "ew_td/sample_chop.h"

using namespace TD;
using namespace ew_td;
using ew::motion::EllipsoidSphericity;

namespace {
bool pointMode(const OP_Inputs* in) { return std::strcmp(in->getParString("Inputmode"), "points") == 0; }
}  // namespace

class EllipsoidSphericityCHOP : public EwSampleChop {
public:
    explicit EllipsoidSphericityCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs* in) const override {
        if (!pointMode(in)) return {Output::scalar("sphericity")};
        return {Output::scalar("sphericity"), Output::scalar("axis_ratio"), Output::indexed("radii", 3)};
    }

    void declareParameters(Params& p) override {
        p.page("Ellipsoid Sphericity");
        p.menu("Inputmode", "Input Mode", "points",
               {{"points", "Point Cloud (PCA Fit)"}, {"sizes", "Direct Ellipsoid Sizes (X,Y,Z)"}});
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        if (!checkSlice(out, in)) return;
        const InputView input = chopInput(in);
        if (pointMode(in)) {
            require(input.channels() % 3 == 0, "Points input requires channels multiple of 3 (x, y, z triplets)");
            const int points = input.channels() / 3;
            std::vector<ew::Point3> cloud(points);
            for (int s = 0; s < out->numSamples; ++s) {
                if (skipNonFinite(input, s)) continue;
                if (points < 2) {
                    setStatus(Status::InvalidInput, "fewer than 2 points");
                    continue;
                }
                for (int i = 0; i < points; ++i) cloud[i] = readPoint(input, i, 3, s);
                const auto fit = EllipsoidSphericity::processPoints(cloud);
                if (fit.radii[0] < 1e-6 || !std::isfinite(fit.sphericity)) {
                    setStatus(Status::InvalidInput, "no extent, or NaN / infinite coordinates");
                    continue;
                }
                out->channels[0][s] = static_cast<float>(fit.sphericity);
                out->channels[1][s] = static_cast<float>(fit.axisRatio);
                out->channels[2][s] = static_cast<float>(fit.radii[0]);
                out->channels[3][s] = static_cast<float>(fit.radii[1]);
                out->channels[4][s] = static_cast<float>(fit.radii[2]);
            }
        } else {
            require(input.channels() >= 3, "Sizes input requires at least 3 channels (sx, sy, sz)");
            for (int s = 0; s < out->numSamples; ++s) {
                const double a = input.at(0, s), b = input.at(1, s), c = input.at(2, s);
                if (!(std::isfinite(a) && std::isfinite(b) && std::isfinite(c) && a > 0 && b > 0 && c > 0)) {
                    setStatus(Status::InvalidInput, "the sizes must be positive and finite");
                    continue;
                }
                out->channels[0][s] = static_cast<float>(EllipsoidSphericity::process(a, b, c));
            }
        }
    }
};

EW_TD_CHOP(EllipsoidSphericityCHOP, "Ewellipsoidsphericity", "EW L2 Ellipsoid Sphericity", 1, 1)

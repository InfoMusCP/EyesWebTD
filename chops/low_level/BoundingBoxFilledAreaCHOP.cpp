// TouchDesigner Bounding Box Filled Area CHOP - wraps ew::motion::BoundingBoxFilledArea
// Input: 3N channels, joint-major (x, y, z per point); every sample is one point cloud.
// Output: 1 channel: contraction_index = area(convex hull) / area(bbox), one sample per input sample.
// A sample with no extent, fewer than 4 points or NaN / infinity: INVALID_INPUT, its output stays 0.
#include <algorithm>
#include <vector>
#include "ew/features/motion/bounding_box_filled_area.h"
#include "ew_td/plugin.h"
#include "ew_td/sample_chop.h"

using namespace TD;
using namespace ew_td;
using ew::motion::BoundingBoxFilledArea;

class BoundingBoxFilledAreaCHOP : public EwSampleChop {
public:
    explicit BoundingBoxFilledAreaCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::scalar("contraction_index")}; }

    void declareParameters(Params& p) override {
        p.page("Bounding Box");
        p.number("Epsilon", "BBox Area Epsilon", 1e-6, Range::atLeast(0.0, 1e-3).withSlider(1e-8, 1e-3));
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        if (!checkSlice(out, in)) return;
        const InputView input = chopInput(in);
        require(input.channels() % 3 == 0, "Input channel count must be a multiple of 3 (x, y, z triplets)");
        const int points = input.channels() / 3;

        BoundingBoxFilledArea::Params p;
        p.epsilon = in->getParDouble("Epsilon");
        const BoundingBoxFilledArea feature(p);

        std::vector<ew::Point3> cloud(points);
        for (int s = 0; s < out->numSamples; ++s) {
            if (skipNonFinite(input, s)) continue;
            for (int i = 0; i < points; ++i) cloud[i] = readPoint(input, i, 3, s);
            double lo[3], hi[3];
            for (int k = 0; k < 3; ++k) {
                lo[k] = hi[k] = input.at(k, s);
                for (int i = 1; i < points; ++i) {
                    lo[k] = std::min(lo[k], input.at(i * 3 + k, s));
                    hi[k] = std::max(hi[k], input.at(i * 3 + k, s));
                }
            }
            const double ex = hi[0] - lo[0], ey = hi[1] - lo[1], ez = hi[2] - lo[2];
            if (2 * (ex * ey + ex * ez + ey * ez) <= p.epsilon) {
                setStatus(Status::InvalidInput, "the bounding box has no extent");
                continue;
            }
            if (points < 4) {
                setStatus(Status::InvalidInput, "fewer than 4 points: the 3D convex hull is degenerate");
                continue;
            }
            try {
                out->channels[0][s] = static_cast<float>(feature.process(cloud));
            } catch (const std::exception& e) {
                setStatus(Status::InvalidInput, e.what());
            }
        }
    }
};

EW_TD_CHOP(BoundingBoxFilledAreaCHOP, "Ewboundingboxfilledarea", "EW L2 Bounding Box Filled Area", 1, 1)

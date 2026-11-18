// TouchDesigner Body Parts From Curvature CHOP - wraps ew::motion::BodyPartsFromCurvature
// Input: 3 channels: curvature, x, y (representing closed contour and its discrete curvature)
// Output: 4 channels: min_x, min_y, max_x, max_y (coordinates of detected curvature extrema), Max Extrema Count samples.
// Buffer with state: the extrema are tracked from one cook to the next; Reset forgets them at the next cook.
#include <cstring>
#include <vector>
#include "ew/features/motion/body_parts_from_curvature.h"
#include "ew_td/buffer_chop.h"
#include "ew_td/plugin.h"
#include "ew_td/slot.h"

using namespace TD;
using namespace ew_td;
using ew::motion::BodyPartsFromCurvature;

class BodyPartsFromCurvatureCHOP : public EwBufferChop {
public:
    explicit BodyPartsFromCurvatureCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override {
        return {Output::scalar("min_x"), Output::scalar("min_y"), Output::scalar("max_x"), Output::scalar("max_y")};
    }

    int numSamples(const OP_Inputs* in) const override {
        const int pointsNumber = in->getParInt("Numberofpoints");
        return pointsNumber > 0 ? pointsNumber : 10;
    }

    void declareParameters(Params& p) override {
        p.page("Body Parts");
        p.integer("Minimumdistance", "Minimum Distance", 5, Range::atLeast(1, 50));
        p.integer("Numberofpoints", "Number of Points", 5, Range::atLeast(0, 30));  // 0: no maxima, all the minima
        p.toggle("Trackpoints", "Track Extrema Points", true);
        p.number("Trackingdistance", "Tracking Distance", 0.05, Range::atLeast(1e-6, 50.0).withSlider(0.01, 10.0));
    }

    void process(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        require(input.channels() >= 3, "Requires 3 channels: curvature, x, y");

        BodyPartsFromCurvature::Params p;
        p.minimumDistance = in->getParInt("Minimumdistance");
        p.numberOfPoints = in->getParInt("Numberofpoints");
        p.trackPoints = in->getParInt("Trackpoints") != 0;
        p.trackingDistance = in->getParDouble("Trackingdistance");
        BodyPartsFromCurvature& feature = feature_.get(p);

        std::vector<double> curvature(input.samples());
        std::vector<ew::Point2> contour(input.samples());
        for (int s = 0; s < input.samples(); ++s) {
            curvature[s] = input.at(0, s);
            contour[s].x = input.at(1, s);
            contour[s].y = input.at(2, s);
        }

        const auto result = feature.process(curvature, contour);
        int index = 0;
        for (const auto& [label, point] : result.minimums) {
            if (index < out->numSamples) {
                out->channels[0][index] = static_cast<float>(point.x);
                out->channels[1][index] = static_cast<float>(point.y);
                ++index;
            }
        }
        index = 0;
        for (const auto& [label, point] : result.maximums) {
            if (index < out->numSamples) {
                out->channels[2][index] = static_cast<float>(point.x);
                out->channels[3][index] = static_cast<float>(point.y);
                ++index;
            }
        }
    }

    void dropState() override { feature_.drop(); }

private:
    FeatureSlot<BodyPartsFromCurvature> feature_;
};

EW_TD_CHOP(BodyPartsFromCurvatureCHOP, "Ewbodypartsfromcurvature", "EW L2 Body Parts From Curvature", 1, 1)

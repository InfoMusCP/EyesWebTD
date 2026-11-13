// TouchDesigner Contour Curvature CHOP - wraps ew::motion::ContourCurvature
// Input: 2 channels (x, y) representing a closed 2D contour of N samples.
// Output: 1 channel (curvature) with N samples representing the discrete curvature.
#include <vector>
#include "ew/features/motion/contour_curvature.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;

class ContourCurvatureCHOP : public EwChop {
public:
    explicit ContourCurvatureCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::scalar("curvature")}; }

    int numSamples(const OP_Inputs* in) const override { return inputSamples(in); }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        requireFinite(input);
        require(input.channels() >= 2, "ContourCurvature requires at least 2 channels (x, y)");

        std::vector<ew::Point2> contour(input.samples());
        for (int s = 0; s < input.samples(); ++s) {
            contour[s].x = input.at(0, s);
            contour[s].y = input.at(1, s);
        }

        const std::vector<double> curvature = curvature_.process(contour);
        for (size_t s = 0; s < curvature.size() && static_cast<int>(s) < out->numSamples; ++s)
            out->channels[0][s] = static_cast<float>(curvature[s]);
    }

private:
    ew::motion::ContourCurvature curvature_;
};

EW_TD_CHOP(ContourCurvatureCHOP, "Ewcontourcurvature", "EW L2 Contour Curvature", 1, 1)

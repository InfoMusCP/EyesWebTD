// TouchDesigner Triangle Symmetry CHOP - wraps ew::motion::TriangleSymmetryIndex
// Input: 6 channels (upper_x, upper_y, left_x, left_y, right_x, right_y)
// Output: 1 channel per input sample, named as the PyEyesWeb output of the method (parameter Method):
//   area: symmetry, 1 = symmetric, 0 = totally asymmetric (EyesWeb's index);
//   horizontal, vertical, spatial: horizontal_asymmetry, vertical_asymmetry, spatial_asymmetry (Glowinski et al. 2011,
//   eqs. 4-5; 0 = symmetric).
// Collinear vertices (area), an undefined Glowinski index (or NaN / infinity): status InvalidInput, output 0
// (that sample only, except NaN / infinity).
#include <cmath>
#include <cstring>
#include "ew/features/motion/triangle_symmetry_index.h"
#include "ew_td/plugin.h"
#include "ew_td/sample_chop.h"

using namespace TD;
using namespace ew_td;

namespace {
constexpr double kCollinear = 1e-9;  // as PyEyesWeb: relative triangle area below which the vertices are collinear

using TSI = ew::motion::TriangleSymmetryIndex;

struct MethodInfo {
    const char* token;
    const char* label;
    const char* output;
    TSI::Method method;
};
constexpr MethodInfo kMethods[] = {
    {"area", "Area (EyesWeb)", "symmetry", TSI::Method::Area},
    {"horizontal", "Horizontal (Glowinski 2011)", "horizontal_asymmetry", TSI::Method::Horizontal},
    {"vertical", "Vertical (Glowinski 2011)", "vertical_asymmetry", TSI::Method::Vertical},
    {"spatial", "Spatial (Glowinski 2011)", "spatial_asymmetry", TSI::Method::Spatial},
};

const MethodInfo& method(const OP_Inputs* in) {
    const char* token = in->getParString("Method");
    for (const MethodInfo& m : kMethods)
        if (token && std::strcmp(token, m.token) == 0) return m;
    return kMethods[0];
}
}  // namespace

class TriangleSymmetryCHOP : public EwSampleChop {
public:
    explicit TriangleSymmetryCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs* in) const override { return {Output::scalar(method(in).output)}; }

    void declareParameters(Params& p) override {
        p.page("Triangle Symmetry");
        p.menu("Method", "Method", "area",
               {{kMethods[0].token, kMethods[0].label}, {kMethods[1].token, kMethods[1].label},
                {kMethods[2].token, kMethods[2].label}, {kMethods[3].token, kMethods[3].label}});
    }


    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        if (!checkSlice(out, in)) return;
        const InputView input = chopInput(in);
        requireFinite(input);
        require(input.channels() >= 6, "TriangleSymmetry requires at least 6 channels: ux, uy, lx, ly, rx, ry");
        TSI::Params params;
        params.method = method(in).method;
        const TSI block(params);

        for (int s = 0; s < out->numSamples; ++s) {
            const ew::Point2 upper{input.at(0, s), input.at(1, s)};
            const ew::Point2 left{input.at(2, s), input.at(3, s)};
            const ew::Point2 right{input.at(4, s), input.at(5, s)};
            if (params.method != TSI::Method::Area) {
                const double value = block.compute(upper, left, right);
                if (std::isnan(value)) {
                    setStatus(Status::InvalidInput, upper.x == left.x && upper.x == right.x
                                                        ? "all vertices on one vertical line"
                                                        : "the two lower vertices at the same height");
                    continue;
                }
                out->channels[0][s] = static_cast<float>(value);
                continue;
            }
            const double toLeftX = left.x - upper.x, toLeftY = left.y - upper.y;
            const double toRightX = right.x - upper.x, toRightY = right.y - upper.y;
            const double area = std::abs(toLeftX * toRightY - toLeftY * toRightX);
            if (area <= kCollinear * std::hypot(toLeftX, toLeftY) * std::hypot(toRightX, toRightY)) {
                setStatus(Status::InvalidInput, "the vertices are collinear");
                continue;
            }
            out->channels[0][s] = static_cast<float>(TSI::process(upper, left, right));
        }
    }
};

EW_TD_CHOP(TriangleSymmetryCHOP, "Ewtrianglesymmetry", "EW L2 Triangle Symmetry", 1, 1)

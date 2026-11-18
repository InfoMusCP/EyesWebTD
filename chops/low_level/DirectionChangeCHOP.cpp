// TouchDesigner Direction Change CHOP - wraps ew::motion::DirectionChange
// Input: 2 or 3 channels (x, y [, z]) representing trajectory points over time, at least 3 samples.
// Output: 2 channels: cosine (sharp change score in [0, 1]) and polygon (area of the subsampled trajectory).
// Fewer than 3 samples: WARMING_UP; NaN or infinity: INVALID_INPUT.
#include "ew/features/motion/direction_change.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;
using ew::motion::DirectionChange;

class DirectionChangeCHOP : public EwChop {
public:
    explicit DirectionChangeCHOP(const OP_NodeInfo*) {}

    // The outputs follow the Cosine and Polygon toggles, as the `metrics` of PyEyesWeb (cosine first).
    Schema schema(const OP_Inputs* in) const override {
        Schema schema;
        const bool cosine = !in || in->getParInt("Cosine") != 0, polygon = !in || in->getParInt("Polygon") != 0;
        if (cosine || !polygon) schema.add(Output::scalar("cosine"));
        if (polygon) schema.add(Output::scalar("polygon"));
        return schema;
    }

    void declareParameters(Params& p) override {
        p.page("Direction Change");
        p.number("Epsilon", "Cosine Epsilon", 0.5, Range::atLeast(0.0001, 1.0).withSlider(0.01, 1.0));
        p.integer("Numberofsubsamples", "Number of Subsamples", 20, Range::atLeast(1, 100).withSlider(3, 100));
        p.toggle("Cosine", "Cosine Metric", true);
        p.toggle("Polygon", "Polygon Metric (area)", true);
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        const int dims = input.channels();
        require(dims >= 2 && dims <= 3, "DirectionChange requires 2 or 3 channels (x, y [, z])");
        if (input.samples() < 3) return windowTooShort(input.samples(), 3);
        requireFinite(input);

        ew::Matrix trajectory(input.samples(), dims);
        for (int s = 0; s < input.samples(); ++s)
            for (int d = 0; d < dims; ++d) trajectory(s, d) = input.at(d, s);

        DirectionChange::Params p;
        p.epsilon = in->getParDouble("Epsilon");
        p.numberOfSubsamples = in->getParInt("Numberofsubsamples");
        const DirectionChange feature(p);

        const bool polygon = in->getParInt("Polygon") != 0, cosine = in->getParInt("Cosine") != 0 || !polygon;
        int channel = 0;
        if (cosine) out->channels[channel++][0] = static_cast<float>(feature.cosine(trajectory));
        if (polygon) out->channels[channel++][0] = static_cast<float>(feature.polygonArea(trajectory));
    }
};

EW_TD_CHOP(DirectionChangeCHOP, "Ewdirectionchange", "EW L2 Direction Change", 1, 1)

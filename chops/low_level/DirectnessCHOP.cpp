// TouchDesigner Directness CHOP - wraps ew::trajectory::Directness
// Directness index of a path: |oldest - newest| / path_length
// Input: 2 or 3 channels (x, y [, z]) across N samples.
// Output: 1 channel: directness_index in [0, 1].
// One point: WARMING_UP; NaN or infinity: INVALID_INPUT.
#include "ew/features/trajectory/directness.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;

class DirectnessCHOP : public EwChop {
public:
    explicit DirectnessCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::scalar("directness_index")}; }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        require(input.channels() >= 2, "Directness requires at least 2 channels (x, y [, z])");
        requireFinite(input);
        if (input.samples() < 2) return warmingUp(input.samples(), 2);
        out->channels[0][0] = static_cast<float>(directness_.process(readTrajectory(input)));
    }

private:
    ew::trajectory::Directness directness_;
};

EW_TD_CHOP(DirectnessCHOP, "Ewdirectness", "EW L2 Directness", 1, 1)

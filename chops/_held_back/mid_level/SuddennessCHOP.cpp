// TouchDesigner Suddenness CHOP - wraps ew::motion::Suddenness (stable distribution fitting).
// Input: one trajectory, Dims channels (x, y, z), like PyEyesWeb; for a skeleton, select the joint first. The whole input
// is one window.
// Output: 4 channels, 1 sample: is_sudden, alpha, beta, gamma (the PyEyesWeb order; 0 while fewer than 6 rows: the
// status is then WARMING_UP; INVALID_INPUT for NaN or infinity and, with Quantile, a window the fit cannot handle).
#include <cstring>
#include <string>
#include <vector>
#include "ew/features/motion/suddenness.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;
using ew::motion::Suddenness;

class SuddennessCHOP : public EwChop {
public:
    static constexpr int kMinRows = 6;

    explicit SuddennessCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override {
        return {Output::scalar("is_sudden"), Output::scalar("alpha"), Output::scalar("beta"), Output::scalar("gamma")};
    }

    void declareParameters(Params& p) override {
        p.page("Suddenness");
        p.menu("Algorithm", "Algorithm", "constrained",
               {{"constrained", "Constrained (EyesWeb)"}, {"quantile", "Quantile"}});
        p.integer("Dims", "Dims", 3, Range::between(1, 4));
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        requireFinite(input);
        const int dims = in->getParInt("Dims") < 1 ? 1 : in->getParInt("Dims");
        require(input.channels() == dims, "Input must be one trajectory: " + std::to_string(dims) + " channels (Dims), got " +
                                              std::to_string(input.channels()));
        const int rows = input.samples();
        if (rows < kMinRows) {
            warmingUp(rows, kMinRows);
            return;
        }

        std::vector<double> positions(static_cast<std::size_t>(rows) * dims);
        for (int t = 0; t < rows; ++t)
            for (int d = 0; d < dims; ++d) positions[static_cast<std::size_t>(t) * dims + d] = input.at(d, t);

        Suddenness::Params p;
        p.method = std::strcmp(in->getParString("Algorithm"), "quantile") == 0 ? Suddenness::Algorithm::Quantile
                                                                                 : Suddenness::Algorithm::Constrained;

        const auto result =
            Suddenness(p).process(positions.data(), static_cast<std::size_t>(rows), static_cast<std::size_t>(dims));
        if (!result) {
            warmingUp(rows, kMinRows);
            return;
        }
        if (result->alpha == -1) {
            setStatus(Status::InvalidInput, "the distribution could not be fitted");
            return;
        }

        out->channels[0][0] = result->isSudden ? 1.f : 0.f;
        out->channels[1][0] = static_cast<float>(result->alpha);
        out->channels[2][0] = static_cast<float>(result->beta);
        out->channels[3][0] = static_cast<float>(result->gamma);
    }
};

EW_TD_CHOP(SuddennessCHOP, "Ewsuddenness", "EW L3 Suddenness", 1, 1)

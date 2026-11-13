// TouchDesigner Ensemble Dominance CHOP - wraps ew::motion::EnsembleDominance
// Input: one channel per participant holding its complexity index (first sample), e.g. from the EW Multi-scale Entropy CHOP.
// Output: dominance<i> per input channel, then leader_index and leader_complexity (1 sample). NaN is data; an infinite
// index is INVALID_INPUT.
#include <cmath>
#include <string>
#include <vector>
#include "ew/features/motion/ensemble_dominance.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;
using ew::motion::EnsembleDominance;

class EnsembleDominanceCHOP : public EwChop {
public:
    explicit EnsembleDominanceCHOP(const OP_NodeInfo*) {}

    // The number of scores follows the input, and PyEyesWeb gives no fixed names for it: the names are the ones the
    // operator always had.
    Schema schema(const OP_Inputs* in) const override {
        const int participants = in->getNumInputs() ? in->getInputCHOP(0)->numChannels : 1;
        Schema s;
        for (int i = 0; i < participants; ++i) s.add(Output::scalar("dominance" + std::to_string(i)));
        s.add(Output::scalar("leader_index"));
        s.add(Output::scalar("leader_complexity"));
        return s;
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        const int n = input.channels();
        std::vector<double> indices(static_cast<size_t>(n));
        for (int c = 0; c < n; ++c) {
            indices[static_cast<size_t>(c)] = input.at(c, 0);
            require(!std::isinf(indices[static_cast<size_t>(c)]), "input contains infinity");
            require(!(indices[static_cast<size_t>(c)] < 0), "negative complexity index");  // as PyEyesWeb
        }

        const auto res = EnsembleDominance().process(indices.data(), indices.size());
        for (int c = 0; c < n; ++c) out->channels[c][0] = static_cast<float>(res.dominanceScore[c]);
        out->channels[n][0] = static_cast<float>(res.leaderIndex);
        out->channels[n + 1][0] = static_cast<float>(res.leaderComplexity);
    }
};

EW_TD_CHOP(EnsembleDominanceCHOP, "Ewensembledominance", "EW L4 Ensemble Dominance", 1, 1)

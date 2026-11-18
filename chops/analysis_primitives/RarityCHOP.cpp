// TouchDesigner Rarity CHOP - wraps ew::motion::NoveltyRarity (PyEyesWeb Rarity, method "novelty").
// How unusual the movement of the last moments is compared with the movement of the recent past, for ANY signal: a scalar
// (a speed, an energy), a position, several features. At every sample the last Pattern seconds are a pattern; it is compared
// with the patterns of the last Memory seconds (the nearest Neighbours of them), and the distance is divided by its own
// median, so the value is dimensionless: about 1 for a movement as familiar as usual, larger for a movement that has not
// happened in the memory. A repeated movement becomes familiar; a movement not done for Memory seconds is new again.
//
// Input: N channels (any signal; the channels are scaled by their own standard deviation). Output: 1 channel, rarity.
//   Source = stream (default): one sample, the rarity of the newest sample (a live source gives 1 or 2 samples in a frame;
//     every sample feeds the memory). Source = clip: one value per input sample.
//   Compare: values (the pattern as it is: level counts, for scalars) or shape (the newest sample is subtracted from the
//     pattern: only the shape counts, not where it happens, for positions).
//   Parameters are in seconds (the sample rate of the input converts them); the points of a pattern are spaced to about 15.
// Statuses: WARMING_UP until the memory holds twice the pattern length of patterns to compare with (the output is 0); a NaN
// or infinite sample is skipped (INVALID_INPUT, not used). Reset forgets the memory; so does a change of the number of
// channels, of the sample rate, of Memory, Pattern, Compare.
// The two EyesWeb / PyEyesWeb methods of Rarity (a bin of the current level, and the distance from the most common bin) stay
// in PyEyesWeb: they are blind to a change of shape inside a bin or of amplitude (design review 2026-11-17).
#include <algorithm>
#include <cmath>
#include <cstring>
#include <string>
#include <vector>
#include "ew/features/motion/novelty_rarity.h"
#include "ew_td/plugin.h"
#include "ew_td/slot.h"
#include "ew_td/stream_chop.h"

using namespace TD;
using namespace ew_td;
using ew::motion::NoveltyRarity;

class RarityCHOP : public EwStreamChop {
public:
    explicit RarityCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::scalar("rarity")}; }

    bool oneSampleInStream() const override { return true; }

    void declareParameters(Params& p) override {
        p.page("Rarity");
        p.number("Memory", "Memory (s)", 5.0, Range::atLeast(0.1, 30.0));
        p.number("Pattern", "Pattern (s)", 0.5, Range::atLeast(0.02, 5.0));
        p.integer("Neighbours", "Neighbours", 5, Range::atLeast(1, 50));
        p.menu("Compare", "Compare", "values", {{"values", "Values (level counts)"}, {"shape", "Shape (position ignored)"}});
    }

    void dropState() override {
        feature_.drop();
        warmup_ = 0;
    }

    void process(CHOP_Output* out, const OP_Inputs* in, const InputView& input) override {
        const double rate = input.sampleRate() > 0 ? input.sampleRate() : 60.0;
        NoveltyRarity::Params p;
        p.channels = input.channels();
        p.pattern = std::max(2, static_cast<int>(std::lround(in->getParDouble("Pattern") * rate)));
        p.memory = std::max(3 * p.pattern, static_cast<int>(std::lround(in->getParDouble("Memory") * rate)));
        p.step = std::max(1, static_cast<int>(std::lround(p.pattern / 15.0)));
        p.neighbours = std::max(1, in->getParInt("Neighbours"));
        p.shape = std::strcmp(in->getParString("Compare"), "shape") == 0;
        NoveltyRarity& feature = feature_.get(p);
        warmup_ = static_cast<int>(feature.warmupSamples());

        const bool single = out->numSamples == 1;  // Stream: the newest sample only; Clip: one value per sample (of the clip)
        std::vector<double> sample(static_cast<size_t>(input.channels()));
        bool filling = false, skipped = false;
        for (int s = 0; s < input.samples(); ++s) {
            if (skipNonFinite(input, s)) {
                skipped = true;
                continue;
            }
            for (int c = 0; c < input.channels(); ++c) sample[static_cast<size_t>(c)] = input.at(c, s);
            const auto rarity = feature.process(sample.data());
            filling = !rarity;
            const int slot = single ? 0 : s;
            if (slot < out->numSamples) out->channels[0][slot] = rarity ? static_cast<float>(*rarity) : 0.f;
        }
        if (filling && !skipped) setStatus(Status::WarmingUp, "the memory is filling (" + std::to_string(warmup_) + " samples before the first value)");
    }

private:
    FeatureSlot<NoveltyRarity> feature_;
    int warmup_ = 0;
};

EW_TD_CHOP(RarityCHOP, "Ewrarity", "EW AP Rarity", 1, 1)

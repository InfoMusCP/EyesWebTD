// TouchDesigner Rarity CHOP - wraps ew::motion::RarityIndex and ew::motion::HistogramRarity
// Method "information" (EyesWeb RarityIndex): input N channels, one sample per cook sample; output rarity_<c> per input
// sample, with the memory kept between cooks. Method "mode_distance" (PyEyesWeb HistogramRarity): the input is the
// window of each channel; output rarity_<c> x 1 sample, WARMING_UP below 2 samples. Reset forgets the memory of the
// information method, which reports WARMING_UP until Memory samples were seen (rarity type) and INVALID_INPUT for a
// value above 1.0 (the bins) or a NaN / infinite sample (skipped, not fed). NaN or infinity in mode_distance: INVALID_INPUT.
#include <sstream>
#include <cstring>
#include <string>
#include <vector>
#include "ew/features/motion/histogram_rarity.h"
#include "ew/features/motion/rarity_index.h"
#include "ew_td/plugin.h"
#include "ew_td/buffer_chop.h"
#include "ew_td/slot.h"

using namespace TD;
using namespace ew_td;
using ew::motion::HistogramRarity;
using ew::motion::RarityIndex;

class RarityCHOP : public EwBufferChop {
public:
    explicit RarityCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs* in) const override {
        return {Output::indexed("rarity", in->getNumInputs() ? in->getInputCHOP(0)->numChannels : 1)};
    }

    int numSamples(const OP_Inputs* in) const override {
        if (!in->getNumInputs()) return 1;
        return isModeDistance(in) ? 1 : in->getInputCHOP(0)->numSamples;
    }

    double sampleRate(const OP_Inputs* in) const override {
        return in->getNumInputs() ? in->getInputCHOP(0)->sampleRate : 60;
    }

    void declareParameters(Params& p) override {
        p.page("Rarity");
        p.menu("Method", "Method", "information",
               {{"information", "Information (EyesWeb)"}, {"mode_distance", "Mode Distance (Histogram)"}});
        p.menu("Measure", "Measure", "rarity", {{"rarity", "Rarity (Time)"}, {"contrast", "Contrast (Space)"}});
        p.integer("Window", "Window (samples)", 50, Range::atLeast(2, 500));
        p.string("Bins", "Bin Widths (information, e.g. 0.3 0.3 0.4)", "0.3 0.3 0.4");
        p.number("Alpha", "Alpha (Histogram Scaling)", 0.5, Range::atLeast(0.0, 10.0));
    }

    void dropState() override {
        ri_.drop();
        seen_ = 0;
    }

    void process(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        if (isModeDistance(in)) {
            requireFinite(input);
            if (input.samples() < 2) setStatus(Status::WarmingUp, "fewer than 2 samples");
            // HistogramRarity: over the window of samples of each channel
            HistogramRarity::Params hp;
            hp.alpha = in->getParDouble("Alpha");
            HistogramRarity hr(hp);
            std::vector<double> smp(input.samples());
            for (int c = 0; c < input.channels() && c < out->numChannels; ++c) {
                for (int s = 0; s < input.samples(); ++s) smp[s] = input.at(c, s);
                const auto res = hr.process(smp.data(), smp.size());
                out->channels[c][0] = res.has_value() ? static_cast<float>(*res) : 0.f;
            }
        } else {
            RarityIndex::Params rp;
            rp.numberOfInputs = input.channels();
            rp.window = in->getParInt("Window");
            {   // the widths of the bins, in the units of the signal; a value above their sum is outside the bins
                std::stringstream list(in->getParString("Bins") ? in->getParString("Bins") : "");
                std::vector<double> widths;
                double width;
                while (list >> width) widths.push_back(width);
                require(!widths.empty(), "Bin Widths needs at least one width");
                rp.bins = widths;
                binsTotal_ = 0;
                for (double w : widths) binsTotal_ += w;
            }
            rp.measure = std::strcmp(in->getParString("Measure"), "contrast") == 0 ? RarityIndex::Type::Contrast
                                                                                    : RarityIndex::Type::Rarity;
            RarityIndex& index = ri_.get(rp);
            std::vector<double> sample(input.channels());
            if (rp.numberOfInputs != lastInputs_ || rp.window != lastMemory_) seen_ = 0;
            lastInputs_ = rp.numberOfInputs;
            lastMemory_ = rp.window;
            const bool usesMemory = rp.measure == RarityIndex::Type::Rarity;
            bool outside = false;
            for (int s = 0; s < input.samples(); ++s) {
                if (skipNonFinite(input, s)) continue;
                for (int c = 0; c < input.channels(); ++c) {
                    sample[c] = input.at(c, s);
                    if (sample[c] > binsTotal_) outside = true;
                }
                const auto res = index.process(sample);
                if (usesMemory) ++seen_;
                for (int c = 0; c < input.channels() && c < out->numChannels; ++c) out->channels[c][s] = static_cast<float>(res[c]);
            }
            if (outside) setStatus(Status::InvalidInput, "value outside the bins");
            else if (usesMemory && seen_ < rp.window && status() == Status::Ok)
                setStatus(Status::WarmingUp, "the memory holds " + std::to_string(seen_) + " of " + std::to_string(rp.window) + " values");
        }
    }

private:
    static bool isModeDistance(const OP_Inputs* in) { return std::strcmp(in->getParString("Method"), "mode_distance") == 0; }

    double binsTotal_ = 1.0;  // the sum of the bin widths (default 0.3 + 0.3 + 0.4)

    FeatureSlot<RarityIndex> ri_;
    int seen_ = 0;
    int lastInputs_ = 0;
    int lastMemory_ = 0;
};

EW_TD_CHOP(RarityCHOP, "Ewrarity", "EW AP Rarity", 1, 1)

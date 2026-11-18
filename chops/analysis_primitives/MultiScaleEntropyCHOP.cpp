// TouchDesigner MultiScale Entropy CHOP - wraps ew::motion::MultiScaleEntropy
// Input: N channels, M samples.
// Output: complexity index per channel (complexity<c>), then the sample entropy of every scale 1..Maxscale per channel
// (entropy<c>_scale<k>, NaN for a scale not used). Feed the complexity indices to the EW Ensemble Dominance CHOP for
// the dominance. A NaN or infinity in the input is INVALID_INPUT. Frame operator: nothing is kept between cooks.
#include <string>
#include <vector>
#include "ew/features/motion/multi_scale_entropy.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;
using ew::motion::MultiScaleEntropy;

class MultiScaleEntropyCHOP : public EwChop {
public:
    explicit MultiScaleEntropyCHOP(const OP_NodeInfo*) {}

    // PyEyesWeb: complexity_index (one per signal) and scale_entropies (signals x scales), both data-dependent in size,
    // so the channel names stay the ones of this operator.
    Schema schema(const OP_Inputs* in) const override {
        const int nch = inputChannels(in);
        const int scales = in->getParInt("Maxscale");
        Schema s;
        for (int c = 0; c < nch; ++c) s.add(Output::scalar("complexity" + std::to_string(c)));
        for (int c = 0; c < nch; ++c)
            for (int k = 0; k < scales; ++k)
                s.add(Output::scalar("entropy" + std::to_string(c) + "_scale" + std::to_string(k + 1)));
        return s;
    }

    void declareParameters(Params& p) override {
        p.page("MSE");
        p.integer("Embeddingdimension", "Embedding Dimension", 2, Range::atLeast(1, 5));
        p.number("Tolerance", "Tolerance", 0.15, Range::atLeast(0.0001, 0.99).withSlider(0.01, 0.99));
        p.integer("Maxscale", "Max Scale", 6, Range::atLeast(1, 20));
        p.integer("Minimumpoints", "Minimum Points", 30, Range::atLeast(5, 1000).withSlider(10, 1000));  // lowered default for live testing
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        requireFinite(input);
        MultiScaleEntropy::Params p;
        p.embeddingDimension = in->getParInt("Embeddingdimension");
        p.tolerance = in->getParDouble("Tolerance");
        p.maxScale = in->getParInt("Maxscale");
        p.minimumPoints = in->getParInt("Minimumpoints");

        const int nch = input.channels(), samples = input.samples();
        std::vector<double> buf(static_cast<size_t>(nch) * samples);
        for (int c = 0; c < nch; ++c)
            for (int s = 0; s < samples; ++s) buf[static_cast<size_t>(c) * samples + s] = input.at(c, s);

        ew::TimeSeriesView tsv;
        tsv.data = buf.data();
        tsv.channels = nch;
        tsv.samples = samples;
        tsv.samplingRate = input.sampleRate();

        MultiScaleEntropy mse(p);
        const auto res = mse.process(tsv);
        if (!res.has_value()) {
            setStatus(Status::WarmingUp, "fewer than Min Points samples");
            return;
        }
        for (int c = 0; c < nch; ++c) {
            out->channels[c][0] = static_cast<float>(res->complexityIndex[c]);
            for (int s = 0; s < p.maxScale; ++s)
                out->channels[nch + c * p.maxScale + s][0] = static_cast<float>(res->scaleEntropies(c, s));
        }
    }

private:
    static int inputChannels(const OP_Inputs* in) { return in->getNumInputs() ? in->getInputCHOP(0)->numChannels : 1; }
};

EW_TD_CHOP(MultiScaleEntropyCHOP, "Ewmultiscaleentropy", "EW AP Multi Scale Entropy", 1, 1)

// TouchDesigner Sample Entropy CHOP - wraps ew::motion::SampleEntropy
// Input: exactly 1 channel time series (NaN or infinity: INVALID_INPUT) (the window to analyse). Output: 1 channel x 1 sample,
// sample_entropy = SampEn(m, r) = -log(A / B) as in the literature (Richman & Moorman 2000): B the pairs of templates of m
// samples that match within r, A those that still match with m + 1 samples. m is the Embedding Dimension (default 2).
// The core computes the values for the template lengths 1 .. m + 1 (pyEntropy); the last one is the SampEn of m.
// Frame operator: nothing is kept between cooks.
#include <vector>
#include "ew/features/motion/sample_entropy.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;
using ew::motion::SampleEntropy;

class SampleEntropyCHOP : public EwChop {
public:
    explicit SampleEntropyCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::scalar("sample_entropy")}; }

    void declareParameters(Params& p) override {
        p.page("Sample Entropy");
        p.integer("Embeddingdimension", "Embedding Dimension (m)", 2, Range::atLeast(1, 10));
        p.toggle("Useabsolutetolerance", "Absolute Tolerance", false);
        p.number("Relativetolerance", "Relative Tolerance (x std)", 0.2, Range::atLeast(0.0001, 2.0).withSlider(0.001, 2.0));
        p.number("Tolerance", "Absolute Tolerance (r)", 0.2, Range::atLeast(0.0001, 2.0).withSlider(0.001, 2.0));
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        require(input.channels() == 1, "SampleEntropy requires 1 channel");
        requireFinite(input);

        SampleEntropy::Params p;
        int m = in->getParInt("Embeddingdimension");
        if (m < 1) m = 1;
        p.embeddingDimension = static_cast<size_t>(m) + 1;  // the core gives the values of the lengths 1 .. m + 1: the last is SampEn(m)
        // As PyEyesWeb: a tolerance times the standard deviation of the window, or an absolute r when asked for.
        p.relativeTolerance = in->getParDouble("Relativetolerance");
        if (in->getParInt("Useabsolutetolerance") != 0) p.tolerance = in->getParDouble("Tolerance");
        require(input.samples() > static_cast<int>(p.embeddingDimension), "Input sample count must exceed embedding dimension");

        std::vector<double> buf(input.samples());
        for (int s = 0; s < input.samples(); ++s) buf[s] = input.at(0, s);

        ew::TimeSeriesView tsv;
        tsv.data = buf.data();
        tsv.channels = 1;
        tsv.samples = input.samples();
        tsv.samplingRate = input.sampleRate();

        SampleEntropy se(p);
        const ew::Matrix res = se.process(tsv);
        out->channels[0][0] = static_cast<float>(res(0, res.cols - 1));
    }
};

EW_TD_CHOP(SampleEntropyCHOP, "Ewsampleentropy", "EW AP Sample Entropy", 1, 1)

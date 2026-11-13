// TouchDesigner Sample Entropy CHOP - wraps ew::motion::SampleEntropy
// Input: exactly 1 channel time series (NaN or infinity: INVALID_INPUT) (the window to analyse). Output: Embeddingdim channels x 1 sample, sample_entropy_k =
// -log(A[k] / B[k]) for template length k + 1. Frame operator: nothing is kept between cooks.
#include <vector>
#include "ew/features/motion/sample_entropy.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;
using ew::motion::SampleEntropy;

class SampleEntropyCHOP : public EwChop {
public:
    explicit SampleEntropyCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs* in) const override {
        int m = in->getParInt("Embeddingdimension");
        if (m < 1) m = 1;
        return {Output::indexed("sample_entropy", m)};
    }

    void declareParameters(Params& p) override {
        p.page("Sample Entropy");
        p.integer("Embeddingdimension", "Embedding Dimension", 2, Range::atLeast(1, 10));
        p.toggle("Useabsolutetolerance", "Absolute Tolerance", false);
        p.number("Relativetolerance", "Relative Tolerance (x std)", 0.2, Range::atLeast(0.0001, 2.0).withSlider(0.001, 2.0));
        p.number("Tolerance", "Absolute Tolerance (r)", 0.2, Range::atLeast(0.0001, 2.0).withSlider(0.001, 2.0));
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        require(input.channels() == 1, "SampleEntropy requires 1 channel");
        requireFinite(input);

        SampleEntropy::Params p;
        p.embeddingDimension = in->getParInt("Embeddingdimension");
        if (p.embeddingDimension < 1) p.embeddingDimension = 1;
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
        tsv.samplingRate = in->getInputCHOP(0)->sampleRate;

        SampleEntropy se(p);
        const ew::Matrix res = se.process(tsv);
        for (size_t col = 0; col < res.cols && static_cast<int>(col) < out->numChannels; ++col)
            out->channels[col][0] = static_cast<float>(res(0, col));
    }
};

EW_TD_CHOP(SampleEntropyCHOP, "Ewsampleentropy", "EW AP Sample Entropy", 1, 1)

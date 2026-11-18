// TouchDesigner Periodicity CHOP - wraps ew::motion::PeriodicityIndex (Sethares Periodicity Transform).
// Input: N channels of a time series over the samples of the window: the input is the window (a Trail CHOP, a File In).
// Output: 2*N channels x Cols samples (period<c>, power<c> pairs per channel, -1 = unused). small2large: Cols = N/2+1 with
// N the samples of the input; mbest: Cols = M. Nothing is kept between cooks. A NaN or infinity, a constant window or
// mbest on fewer than 3 samples: INVALID_INPUT, -1 everywhere. The algorithm is the one of the core, unchanged.
// The channel names stay the ones of this operator: PyEyesWeb's periods and powers have a data-dependent size.
#include <algorithm>
#include <cmath>
#include <cstring>
#include <string>
#include <vector>
#include "ew/common/matrix.h"
#include "ew/common/time_series.h"
#include "ew/features/motion/periodicity_index.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;
using ew::motion::PeriodicityIndex;

class PeriodicityCHOP : public EwChop {
public:
    explicit PeriodicityCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs* in) const override {
        const int nch = in->getNumInputs() ? in->getInputCHOP(0)->numChannels : 1;
        Schema s;
        for (int c = 0; c < nch; ++c) {
            s.add(Output::scalar("period" + std::to_string(c)));
            s.add(Output::scalar("power" + std::to_string(c)));
        }
        return s;
    }

    int numSamples(const OP_Inputs* in) const override {
        const PeriodicityIndex::Params p = readParams(in);
        return p.method == PeriodicityIndex::Algorithm::Small2Large ? inputSamples(in) / 2 + 1 : std::max(p.bestPeriods, 0);
    }

    bool needsInput() const override { return false; }

    void declareParameters(Params& p) override {
        p.page("Periodicity");
        p.menu("Method", "Method", "small2large", {{"small2large", "Small to Large"}, {"mbest", "M-Best"}});
        p.number("Threshold", "Threshold (small2large)", 0.1, Range::atLeast(0, 1));
        p.integer("Bestperiods", "Best Periods", 3, Range::between(1, 32));
        p.toggle("Sortbypower", "Sort by power", false);
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        fill(out, -1.f);
        if (in->getNumInputs() == 0) {
            setStatus(Status::NoOutput, "no input");
            return;
        }
        const InputView input = chopInput(in);
        const int nCh = input.channels();
        require(nCh >= 1, "Requires at least 1 input channel");
        const PeriodicityIndex::Params p = readParams(in);
        const int window = input.samples();
        if (window < 8) return windowTooShort(window, 8);
        if (!input.finite()) {
            setStatus(Status::InvalidInput, "input contains NaN or infinity");
            return;
        }

        std::vector<double> frame(static_cast<size_t>(nCh) * window);
        for (int c = 0; c < nCh; ++c)
            for (int t = 0; t < window; ++t) frame[static_cast<size_t>(c) * window + t] = input.at(c, t);

        // As PyEyesWeb: no period to find when every channel is constant, or mbest on fewer than 3 samples.
        int constant = 0;
        for (int c = 0; c < nCh; ++c) {
            const auto first = frame.begin() + static_cast<std::ptrdiff_t>(c) * window;
            const auto [lo, hi] = std::minmax_element(first, first + window);
            if (*lo == *hi) ++constant;
        }
        if (constant == nCh) {
            setStatus(Status::InvalidInput, "constant window: no period");
            return;
        }

        ew::TimeSeriesView tsv;
        tsv.data = frame.data();
        tsv.channels = static_cast<size_t>(nCh);
        tsv.samples = static_cast<size_t>(window);
        tsv.samplingRate = input.sampleRate();
        const ew::Matrix result = PeriodicityIndex(p).process(tsv);
        const int cols = static_cast<int>(result.cols);
        for (int c = 0; c < out->numChannels && c < static_cast<int>(result.rows); ++c)
            for (int s = 0; s < out->numSamples && s < cols; ++s) {
                const double v = result(static_cast<size_t>(c), static_cast<size_t>(s));
                out->channels[c][s] = std::isnan(v) ? 0.f : static_cast<float>(v);  // mbest: NaN power of a constant channel
            }
    }

private:
    static PeriodicityIndex::Params readParams(const OP_Inputs* in) {
        PeriodicityIndex::Params p;
        p.method = std::strcmp(in->getParString("Method"), "mbest") == 0 ? PeriodicityIndex::Algorithm::MBest
                                                                           : PeriodicityIndex::Algorithm::Small2Large;
        p.threshold = in->getParDouble("Threshold");
        p.bestPeriods = in->getParInt("Bestperiods");
        p.sortByPower = in->getParInt("Sortbypower") != 0;
        return p;
    }
    static void fill(CHOP_Output* out, float v) {
        for (int c = 0; c < out->numChannels; ++c)
            for (int s = 0; s < out->numSamples; ++s) out->channels[c][s] = v;
    }
};

EW_TD_CHOP(PeriodicityCHOP, "Ewperiodicity", "EW AP Periodicity", 1, 1)

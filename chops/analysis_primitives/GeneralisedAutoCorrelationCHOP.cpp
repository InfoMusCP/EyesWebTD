// TouchDesigner Generalised Auto-Correlation CHOP - wraps ew::sync::GeneralisedAutoCorrelation
// Recurrence rate RR(tau) of a multichannel series, as a function of the lag tau or at one lag.
// Input: C channels x N samples (the window to analyse).
// Output: 1 channel (recurrence_rate) of Max Lag samples (lags 1..Max Lag), or 1 sample in scalar mode. A lag not
// smaller than the number of samples is INVALID_INPUT (no silent clamping, as PyEyesWeb).
// Frame operator: the window is the CHOP content, nothing is kept between cooks.
#include <algorithm>
#include <cstring>
#include <vector>
#include "ew/common/time_series.h"
#include "ew/features/sync/generalised_auto_correlation.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;
using ew::TimeSeriesView;
using ew::sync::GeneralisedAutoCorrelation;

class GeneralisedAutoCorrelationCHOP : public EwChop {
public:
    explicit GeneralisedAutoCorrelationCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::scalar("recurrence_rate")}; }

    int numSamples(const OP_Inputs* in) const override {
        return isScalar(in) ? 1 : std::max(1, in->getParInt("Maxlag"));
    }

    void declareParameters(Params& p) override {
        p.page("Auto-Correlation");
        p.menu("Outputtype", "Output Type", "function",
               {{"function", "Function of Tau (Array)"}, {"scalar", "Scalar RR(tau)"}});
        p.number("Epsilon", "Recurrence Threshold (Epsilon)", 0.1, Range::atLeast(0.0001, 1.0).withSlider(0.001, 1.0));
        p.integer("Maxlag", "Max Lag (samples)", 10, Range::atLeast(1, 100));
        p.integer("Lag", "Lag (samples)", 1, Range::atLeast(1, 100));
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        requireFinite(input);

        GeneralisedAutoCorrelation::Params p;
        p.epsilon = in->getParDouble("Epsilon");
        p.outputType = isScalar(in) ? GeneralisedAutoCorrelation::OutputType::Scalar
                                    : GeneralisedAutoCorrelation::OutputType::FunctionOfTau;
        p.lag = in->getParInt("Lag");
        p.maxLag = in->getParInt("Maxlag");

        const int n = input.samples();
        std::vector<double> buf(static_cast<size_t>(input.channels()) * n);
        for (int c = 0; c < input.channels(); ++c)
            for (int s = 0; s < n; ++s) buf[static_cast<size_t>(c) * n + s] = input.at(c, s);
        const TimeSeriesView series{buf.data(), static_cast<size_t>(input.channels()), static_cast<size_t>(n),
                                    input.sampleRate()};

        GeneralisedAutoCorrelation feature(p);
        const std::vector<double> result = feature.process(series);
        for (size_t s = 0; s < result.size() && static_cast<int>(s) < out->numSamples; ++s)
            out->channels[0][s] = static_cast<float>(result[s]);
    }

private:
    static bool isScalar(const OP_Inputs* in) { return std::strcmp(in->getParString("Outputtype"), "scalar") == 0; }
};

EW_TD_CHOP(GeneralisedAutoCorrelationCHOP, "Ewgeneralisedautocorrelation", "EW AP Generalised Auto Correlation", 1, 1)

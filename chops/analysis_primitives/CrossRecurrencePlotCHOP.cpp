// TouchDesigner Cross Recurrence Plot CHOP - wraps ew::sync::CrossRecurrencePlot (PyEyesWeb CrossRecurrencePlot)
// Binary cross-recurrence matrix of two multichannel series: entry (i, j) is 1 when the state x_i of the first series is
// within Epsilon of the state y_j of the second (Minkowski norm of order Order; a distance equal to Epsilon is 1).
// This operator takes over the second-input role that the Recurrence Plot CHOP had in the old plugins.
// Input 0: C channels x N1 samples (first series). Input 1: C channels x N2 samples (second series, same C; N2 may
// differ from N1).
// Output: N1 channels x N2 samples: channel i, sample j = recurrence(i, j) (channels named cross_recurrence_matrix_<i>).
// Frame operator: the series are the CHOP contents, nothing is kept between cooks. A NaN or infinity in either input is
// INVALID_INPUT, and so is a different channel count. One Epsilon for every row, as in PyEyesWeb and the core.
#include <vector>
#include "ew/common/matrix.h"
#include "ew/common/time_series.h"
#include "ew/features/sync/cross_recurrence_plot.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;
using ew::Matrix;
using ew::TimeSeriesView;
using ew::sync::CrossRecurrencePlot;

class CrossRecurrencePlotCHOP : public EwChop {
public:
    explicit CrossRecurrencePlotCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs* in) const override {
        return {Output::indexed("cross_recurrence_matrix", inputSamples(in, 0))};
    }
    int numSamples(const OP_Inputs* in) const override { return inputSamples(in, 1); }

    void declareParameters(Params& p) override {
        p.page("Cross Recurrence Plot");
        p.number("Epsilon", "Recurrence Epsilon", 0.5, Range::atLeast(0.0, 5.0).withSlider(0.001, 5.0));
        p.number("Order", "Minkowski Norm Order", 2.0, Range::atLeast(0.0, 10.0));
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView first = chopInput(in, 0);
        const InputView second = chopInput(in, 1);
        require(first.channels() == second.channels(), "The two inputs must have the same number of channels");
        requireFinite(first);
        requireFinite(second);

        CrossRecurrencePlot::Params p;
        p.epsilon = in->getParDouble("Epsilon");
        p.order = in->getParDouble("Order");

        const std::vector<double> a = channelMajor(first), b = channelMajor(second);
        const TimeSeriesView x{a.data(), static_cast<size_t>(first.channels()), static_cast<size_t>(first.samples()),
                               first.sampleRate()};
        const TimeSeriesView y{b.data(), static_cast<size_t>(second.channels()), static_cast<size_t>(second.samples()),
                               second.sampleRate()};
        const Matrix mat = CrossRecurrencePlot(p).process(x, y);
        for (size_t r = 0; r < mat.rows && static_cast<int>(r) < out->numChannels; ++r)
            for (size_t c = 0; c < mat.cols && static_cast<int>(c) < out->numSamples; ++c)
                out->channels[r][c] = static_cast<float>(mat(r, c));
    }

private:
    static std::vector<double> channelMajor(const InputView& v) {
        std::vector<double> buf(static_cast<size_t>(v.channels()) * v.samples());
        for (int c = 0; c < v.channels(); ++c)
            for (int s = 0; s < v.samples(); ++s) buf[static_cast<size_t>(c) * v.samples() + s] = v.at(c, s);
        return buf;
    }
};

EW_TD_CHOP(CrossRecurrencePlotCHOP, "Ewcrossrecurrenceplot", "EW AP Cross Recurrence Plot", 2, 2)

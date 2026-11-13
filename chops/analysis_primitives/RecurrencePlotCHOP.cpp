// TouchDesigner Recurrence Plot CHOP - wraps ew::sync::RecurrencePlot
// Binary recurrence matrix of a multichannel series: 1 where two samples are within Epsilon (Minkowski norm).
// Input: C channels x N samples (the series to analyse).
// Output: N channels x N samples: channel i, sample j = recurrence(i, j) (channels named recurrence_matrix_<i>).
// Frame operator: the series is the CHOP content, nothing is kept between cooks.
#include <sstream>
#include <vector>
#include "ew/common/matrix.h"
#include "ew/common/time_series.h"
#include "ew/features/sync/recurrence_plot.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;
using ew::Matrix;
using ew::TimeSeriesView;
using ew::sync::RecurrencePlot;

class RecurrencePlotCHOP : public EwChop {
public:
    explicit RecurrencePlotCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs* in) const override { return {Output::indexed("recurrence_matrix", inputSamples(in))}; }
    int numSamples(const OP_Inputs* in) const override { return inputSamples(in); }

    void declareParameters(Params& p) override {
        p.page("Recurrence Plot");
        p.number("Epsilon", "Recurrence Epsilon", 0.5, Range::atLeast(0.0, 5.0).withSlider(0.001, 5.0));
        p.number("Order", "Minkowski Norm Order", 2.0, Range::atLeast(0.0, 10.0));
        p.string("Rowepsilons", "Epsilon per sample (e.g. 0.5 0.4 ...; empty = Epsilon for all)", "");
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        requireFinite(input);

        RecurrencePlot::Params p;
        p.epsilon = in->getParDouble("Epsilon");
        p.order = in->getParDouble("Order");
        {   // one threshold per sample (row), as PyEyesWeb `multiple_epsilons`; the count must equal the samples
            std::stringstream list(in->getParString("Rowepsilons") ? in->getParString("Rowepsilons") : "");
            std::vector<double> values;
            double value;
            while (list >> value) values.push_back(value);
            if (!values.empty()) {
                require(static_cast<int>(values.size()) == input.samples(), "Epsilon per sample needs one value per sample");
                p.useMultipleEpsilons = true;
                p.multipleEpsilons = values;
            }
        }

        const int n = input.samples();
        std::vector<double> buf(static_cast<size_t>(input.channels()) * n);
        for (int c = 0; c < input.channels(); ++c)
            for (int s = 0; s < n; ++s) buf[static_cast<size_t>(c) * n + s] = input.at(c, s);
        const TimeSeriesView series{buf.data(), static_cast<size_t>(input.channels()), static_cast<size_t>(n),
                                    input.sampleRate()};

        const RecurrencePlot plot(p);
        const Matrix mat = plot.process(series);
        for (size_t r = 0; r < mat.rows && static_cast<int>(r) < out->numChannels; ++r)
            for (size_t c = 0; c < mat.cols && static_cast<int>(c) < out->numSamples; ++c)
                out->channels[r][c] = static_cast<float>(mat(r, c));
    }
};

EW_TD_CHOP(RecurrencePlotCHOP, "Ewrecurrenceplot", "EW AP Recurrence Plot", 1, 1)

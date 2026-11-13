// TouchDesigner Periodicity CHOP - wraps ew::motion::PeriodicityIndex (Sethares Periodicity Transform).
// Input: N channels of a time series. Output: 2*N channels x Cols samples (period<c>, power<c> pairs per channel,
// -1 = unused). small2large: Cols = Window/2+1; mbest: Cols = M. The last Window samples are kept and the result is
// refreshed every Hop input samples once Window samples were seen. Reset forgets the window. A sample with a NaN or
// infinite channel is skipped (INVALID_INPUT, not buffered). A change of Window, Algorithm or M restarts the window
// (PyEyesWeb keeps the newest samples on a Window change); Threshold is live.
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
#include "ew_td/buffer_chop.h"

using namespace TD;
using namespace ew_td;
using ew::motion::PeriodicityIndex;

class PeriodicityCHOP : public EwBufferChop {
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
        return p.method == PeriodicityIndex::Algorithm::Small2Large ? in->getParInt("Window") / 2 + 1
                                                                       : std::max(p.bestPeriods, 0);
    }

    bool needsInput() const override { return false; }

    void declareParameters(Params& p) override {
        p.page("Periodicity");
        p.menu("Method", "Method", "small2large", {{"small2large", "Small to Large"}, {"mbest", "M-Best"}});
        p.integer("Window", "Window (samples)", 128, Range::between(8, 8192));
        p.integer("Hop", "Hop (samples)", 32, Range::between(1, 8192));
        p.number("Threshold", "Threshold (small2large)", 0.1, Range::atLeast(0, 1));
        p.integer("Bestperiods", "Best Periods", 3, Range::between(1, 32));
        p.toggle("Sortbypower", "Sort by power", false);
    }

    void dropState() override {
        buf_.clear();
        lastResult_.clear();
        bufPos_ = hopCount_ = 0;
    }

    void process(CHOP_Output* out, const OP_Inputs* in) override {
        if (in->getNumInputs() == 0) {
            fill(out, -1.f);
            setStatus(Status::NoOutput, "no input");
            return;
        }
        const InputView input = chopInput(in);
        const int nCh = input.channels();
        require(nCh >= 1, "Requires at least 1 input channel");
        const PeriodicityIndex::Params p = readParams(in);

        const int window = in->getParInt("Window");
        const int hop = in->getParInt("Hop");

        if (buf_.size() != static_cast<size_t>(nCh) * window || lastParams_.method != p.method ||
            lastParams_.bestPeriods != p.bestPeriods) {
            buf_.assign(static_cast<size_t>(nCh) * window, 0.0);
            bufPos_ = 0;
            hopCount_ = 0;
            lastResult_.assign(static_cast<size_t>(out->numChannels) * out->numSamples, -1.0);
        }
        lastParams_ = p;

        const PeriodicityIndex idx(p);
        std::vector<double> frame(static_cast<size_t>(nCh) * window);
        bool evaluated = false;
        std::string invalid;
        for (int s = 0; s < input.samples(); ++s) {
            if (skipNonFinite(input, s)) continue;
            const int slot = bufPos_ % window;
            for (int c = 0; c < nCh; ++c) buf_[static_cast<size_t>(c) * window + slot] = input.at(c, s);
            ++bufPos_;
            ++hopCount_;
            if (bufPos_ < window || hopCount_ < hop) continue;
            hopCount_ = 0;
            // Linearise the ring buffer into a time-ordered frame
            for (int c = 0; c < nCh; ++c)
                for (int t = 0; t < window; ++t)
                    frame[static_cast<size_t>(c) * window + t] = buf_[static_cast<size_t>(c) * window + (bufPos_ + t) % window];

            ew::TimeSeriesView tsv;
            tsv.data = frame.data();
            tsv.channels = static_cast<size_t>(nCh);
            tsv.samples = static_cast<size_t>(window);
            tsv.samplingRate = input.sampleRate();

            // As PyEyesWeb: no period to find when every channel is constant, or mbest on fewer than 3 samples.
            int constant = 0;
            for (int c = 0; c < nCh; ++c) {
                const auto first = frame.begin() + static_cast<std::ptrdiff_t>(c) * window;
                const auto [lo, hi] = std::minmax_element(first, first + window);
                if (*lo == *hi) ++constant;
            }
            if (constant == nCh || (p.method == PeriodicityIndex::Algorithm::MBest && window < 3)) {
                std::fill(lastResult_.begin(), lastResult_.end(), -1.0);
                invalid = constant == nCh ? "constant window: no period" : "mbest needs at least 3 samples";
                evaluated = true;
                continue;
            }
            invalid.clear();
            const ew::Matrix result = idx.process(tsv);
            lastResult_.resize(result.rows * result.cols, -1.0);
            for (size_t r = 0; r < result.rows; ++r)
                for (size_t col = 0; col < result.cols; ++col)  // mbest gives NaN powers for a constant channel
                    lastResult_[r * result.cols + col] = std::isnan(result(r, col)) ? 0.0 : result(r, col);
            lastCols_ = static_cast<int>(result.cols);
            evaluated = true;
        }

        for (int c = 0; c < out->numChannels; ++c)
            for (int s = 0; s < out->numSamples; ++s) {
                const int i = c * lastCols_ + s;
                out->channels[c][s] = (s < lastCols_ && i < static_cast<int>(lastResult_.size())) ? static_cast<float>(lastResult_[i]) : -1.f;
            }
        if (!evaluated) setStatus(bufPos_ < window ? Status::WarmingUp : Status::NoOutput, "");
        else if (!invalid.empty()) setStatus(Status::InvalidInput, invalid);
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

    std::vector<double> buf_;
    std::vector<double> lastResult_;
    PeriodicityIndex::Params lastParams_{};
    int bufPos_ = 0;
    int hopCount_ = 0;
    int lastCols_ = 0;
};

EW_TD_CHOP(PeriodicityCHOP, "Ewperiodicity", "EW AP Periodicity", 1, 1)

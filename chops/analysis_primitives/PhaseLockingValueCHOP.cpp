// TouchDesigner Phase Locking Value CHOP - wraps ew::sync::PhaseLockingValue
// Phase synchrony of two signals from their Hilbert analytic signals, with an optional bandpass filter.
// Input: 2 channels (seriesX, seriesY) of equal length.
// Output: 1 channel, 1 sample: phase_locking_value in [0, 1].
// Frame operator: the window is the CHOP content, nothing is kept between cooks.
#include <cmath>
#include <vector>
#include "ew/features/sync/phase_locking_value.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;
using ew::sync::PhaseLockingValue;

class PhaseLockingValueCHOP : public EwChop {
public:
    explicit PhaseLockingValueCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::scalar("phase_locking_value")}; }

    void declareParameters(Params& p) override {
        p.page("PLV");
        p.toggle("Usefilter", "Apply Bandpass Filter", false);
        p.number("Lowfrequency", "Low Frequency (Hz)", 0.5, Range::atLeast(0.001, 10.0).withSlider(0.01, 10.0));
        p.number("Highfrequency", "High Frequency (Hz)", 4.0, Range::atLeast(0.01, 30.0).withSlider(0.5, 30.0));
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        requireFinite(input);
        require(input.channels() >= 2, "PhaseLockingValue requires at least 2 channels");

        const int n = input.samples();
        std::vector<double> sx(n), sy(n);
        for (int s = 0; s < n; ++s) {
            sx[s] = input.at(0, s);
            sy[s] = input.at(1, s);
        }

        PhaseLockingValue::Params p;
        if (in->getParInt("Usefilter") != 0) {
            PhaseLockingValue::BandPass bp;
            bp.lowcut = in->getParDouble("Lowfrequency");
            bp.highcut = in->getParDouble("Highfrequency");
            bp.fs = input.sampleRate();
            p.filter = bp;
        }

        const PhaseLockingValue feature(p);
        const double plv = feature.process(sx, sy);
        if (std::isnan(plv)) {  // as PyEyesWeb: a constant signal has no phase
            out->channels[0][0] = 0.f;
            setStatus(Status::InvalidInput, "constant signal: no phase");
            return;
        }
        out->channels[0][0] = static_cast<float>(plv);
    }
};

EW_TD_CHOP(PhaseLockingValueCHOP, "Ewphaselockingvalue", "EW AP Phase Locking Value", 1, 1)

// TouchDesigner Curvature Velocity Correlation CHOP - wraps ew::motion::SmoothnessIndex
// Input: 1, 2, or 3 channels (x, y, z trajectory data), a window of samples.
// Output: 5 channels, as the PyEyesWeb outputs, with as many samples as the input: smoothness, curvature, velocity,
//   log_curvature_std, log_speed_std. curvature and velocity carry one value per input sample (velocity per second
//   unless Differentiate is on, as PyEyesWeb); the scalars repeat their value in every sample. The index is on the
//   logarithms of curvature and speed (Mazzarino 2009, Piana 2016): Simplified (default) 1 / (std log k * std log v),
//   capped at Upperlimit; Pearson the correlation of the logarithms.
// Fewer than Filterwindow + 1 samples: status WarmingUp ("k of N samples"), output 0. The first window of a given shape
//   (the filters have no history yet) is WarmingUp ("the filters need a previous window"). A window where curvature or
//   speed does not vary (nothing to correlate), or with a non-finite series, is InvalidInput.
// Parameters: Filterwindowlength (odd, >=5), Filterpolyorder (>=3), Differentiate toggle, Standarddeviationthreshold,
//   Upperlimit, Correlationtype (simplified/pearson), Inputkind (static/stream); defaults as PyEyesWeb.
// A change of Filterwindow, Filterpoly, Differentiate, Inputkind or of the input sample rate restarts the filters (WarmingUp).
// NaN / infinity in the input: InvalidInput, nothing reaches the filters.
// Buffer with state: the Savitzky-Golay filters of the core live between cooks; Reset forgets them at the next cook.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <string>
#include <vector>
#include "ew/common/time_series.h"
#include "ew/features/motion/smoothness_index.h"
#include "ew_td/buffer_chop.h"
#include "ew_td/plugin.h"
#include "ew_td/slot.h"

using namespace TD;
using namespace ew_td;
using ew::motion::SmoothnessIndex;

class CurvatureVelocityCorrelationCHOP : public EwBufferChop {
public:
    explicit CurvatureVelocityCorrelationCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override {
        return {Output::scalar("smoothness"), Output::scalar("curvature"), Output::scalar("velocity"),
                Output::scalar("log_curvature_std"), Output::scalar("log_speed_std")};
    }

    int numSamples(const OP_Inputs* in) const override { return in->getNumInputs() > 0 ? chopInput(in).samples() : 1; }

    void declareParameters(Params& p) override {
        p.page("Curvature Velocity Correlation");
        p.integer("Filterwindowlength", "Filter Window Length (odd)", 9, Range::between(5, 201));
        p.integer("Filterpolyorder", "Filter Polyorder", 3, Range::between(3, 10));
        p.toggle("Differentiate", "Differentiate", false);
        p.number("Standarddeviationthreshold", "Standard Deviation Threshold", 0.0001, Range::atLeast(0, 100));
        p.number("Upperlimit", "Upper Limit", 100.0, Range::atLeast(0, 1e6));
        p.menu("Correlationtype", "Correlation Type", "simplified",
               {{"simplified", "Simplified: 1 / (std log k * std log v)"}, {"pearson", "Pearson of the logarithms"}});
        p.menu("Inputkind", "Input Kind", "stream", {{"stream", "Stream"}, {"static", "Static"}});
    }

    void process(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        requireFinite(input);
        require(input.channels() >= 1 && input.channels() <= 3, "SmoothnessIndex requires 1, 2 or 3 input channels");

        SmoothnessIndex::Params p;
        p.filterWindowLength = ensureOdd(std::max(5, in->getParInt("Filterwindowlength")));
        p.filterPolyorder = std::max(3, in->getParInt("Filterpolyorder"));
        if (p.filterPolyorder >= p.filterWindowLength) p.filterPolyorder = p.filterWindowLength - 1;
        p.differentiate = in->getParInt("Differentiate") != 0;
        p.standardDeviationThreshold = in->getParDouble("Standarddeviationthreshold");
        p.upperLimit = in->getParDouble("Upperlimit");
        p.correlationType = std::strcmp(in->getParString("Correlationtype"), "pearson") == 0
                                ? SmoothnessIndex::CorrelationType::Pearson
                                : SmoothnessIndex::CorrelationType::Simplified;
        p.inputKind = std::strcmp(in->getParString("Inputkind"), "static") == 0 ? SmoothnessIndex::InputKind::Static
                                                                                : SmoothnessIndex::InputKind::Dynamic;
        p = SmoothnessIndex::applyParameterRules(p);

        const int samples = input.samples(), channels = input.channels();
        if (input.sampleRate() != lastRate_) dropState();
        lastRate_ = input.sampleRate();
        if (samples < p.filterWindowLength + 1) {
            setStatus(Status::WarmingUp, std::to_string(samples) + " of " + std::to_string(p.filterWindowLength + 1) + " samples");
            return;
        }
        const std::array<int, 4> structure{p.filterWindowLength, p.filterPolyorder, p.differentiate ? 1 : 0,
                                           p.inputKind == SmoothnessIndex::InputKind::Static ? 1 : 0};
        if (structure != lastStructure_) lastChannels_ = lastSamples_ = 0;
        lastStructure_ = structure;
        SmoothnessIndex& feature = feature_.get(p);
        std::vector<double> data(static_cast<std::size_t>(channels) * samples);
        for (int c = 0; c < channels; ++c)
            for (int s = 0; s < samples; ++s) data[static_cast<std::size_t>(c) * samples + s] = input.at(c, s);

        ew::TimeSeriesView series;
        series.data = data.data();
        series.channels = static_cast<std::size_t>(channels);
        series.samples = static_cast<std::size_t>(samples);
        series.samplingRate = input.sampleRate();

        const SmoothnessIndex::Output result = feature.process(series, 0);
        const bool newShape = channels != lastChannels_ || samples != lastSamples_;
        lastChannels_ = channels;
        lastSamples_ = samples;
        if (newShape) {  // no output: the outputs stay zero
            setStatus(Status::WarmingUp, "the filters need a previous window");
            return;
        }
        require(!std::isnan(result.smoothness), "nothing to correlate: curvature or velocity does not vary, or fewer than "
                                                "3 samples have a non-zero curvature and speed");
        bool finite = true;
        for (double v : result.curvature) finite = finite && std::isfinite(v);
        for (double v : result.velocity) finite = finite && std::isfinite(v);
        require(finite, "curvature or velocity is not finite (values too large)");

        const double velocityScale = p.differentiate ? 1.0 : input.sampleRate();
        for (int s = 0; s < samples; ++s) {
            const std::size_t i = static_cast<std::size_t>(s);
            out->channels[0][s] = static_cast<float>(result.smoothness);
            if (i < result.curvature.size()) out->channels[1][s] = static_cast<float>(result.curvature[i]);
            if (i < result.velocity.size()) out->channels[2][s] = static_cast<float>(result.velocity[i] * velocityScale);
            out->channels[3][s] = static_cast<float>(result.curvatureStd);  // of the logarithms: no rate scaling
            out->channels[4][s] = static_cast<float>(result.velocityStd);
        }
    }

    void dropState() override {
        feature_.drop();
        lastChannels_ = lastSamples_ = 0;
        lastStructure_ = {};
    }

private:
    static int ensureOdd(int v) { return v % 2 == 0 ? v + 1 : v; }

    FeatureSlot<SmoothnessIndex> feature_;
    int lastChannels_ = 0, lastSamples_ = 0;
    double lastRate_ = 0.0;
    std::array<int, 4> lastStructure_{};
};

EW_TD_CHOP(CurvatureVelocityCorrelationCHOP, "Ewcurvaturevelocitycorrelation", "EW L2 Curvature Velocity Correlation", 1, 1)

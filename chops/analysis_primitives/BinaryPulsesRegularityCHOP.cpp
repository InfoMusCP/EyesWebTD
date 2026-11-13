// TouchDesigner Binary Pulses Regularity CHOP - wraps ew::base::BinaryPulsesRegularity.
// Input: 1 channel, a pulse train (a non-zero sample is a pulse). The CHOP keeps the last Window samples and evaluates
// them every Hop input samples. Output: 3 channels x 1 sample (is_regular, pulse_count, is_regularity_detected),
// refreshed when a window is evaluated; is_regularity_detected is 1 only on the evaluation that follows a non-regular
// window. Reset forgets the window and the state of the feature. A NaN or infinite sample is skipped (INVALID_INPUT,
// not buffered). A change of Window restarts the window (PyEyesWeb keeps the newest samples); Threshold is live.
#include <vector>
#include "ew/common/time_series.h"
#include "ew/features/base/binary_pulses_regularity.h"
#include "ew_td/plugin.h"
#include "ew_td/buffer_chop.h"
#include "ew_td/slot.h"

using namespace TD;
using namespace ew_td;
using ew::base::BinaryPulsesRegularity;

class BinaryPulsesRegularityCHOP : public EwBufferChop {
public:
    explicit BinaryPulsesRegularityCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override {
        return {Output::scalar("is_regular"), Output::scalar("pulse_count"), Output::scalar("is_regularity_detected")};
    }

    void declareParameters(Params& p) override {
        p.page("Pulses");
        p.integer("Window", "Window (samples)", 30, Range::atLeast(3, 8192));
        p.integer("Hop", "Hop (samples)", 1, Range::atLeast(1, 8192));
        p.integer("Threshold", "Threshold (samples, spread below it)", 1, Range::atLeast(1, 20));
    }

    void dropState() override {
        block_.drop();
        window_ = 0;
        buffer_.clear();
        pushed_ = hopCount_ = 0;
        last_[0] = last_[1] = last_[2] = 0.0;
    }

    void process(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        require(input.channels() == 1, "Requires 1 input channel");

        BinaryPulsesRegularity::Params p;
        p.threshold = in->getParInt("Threshold");
        const int window = in->getParInt("Window");
        const int hop = in->getParInt("Hop");

        if (block_.empty() || window_ != window) {
            block_.drop();
            window_ = window;
            buffer_.assign(static_cast<size_t>(window), 0.0);
            pushed_ = hopCount_ = 0;
            last_[0] = last_[1] = last_[2] = 0.0;
        }
        BinaryPulsesRegularity& feature = block_.get(p);  // the threshold is live

        std::vector<double> ordered(static_cast<size_t>(window));  // oldest sample first
        bool evaluated = false;
        for (int s = 0; s < input.samples(); ++s) {
            if (skipNonFinite(input, s)) continue;
            buffer_[static_cast<size_t>(pushed_ % window)] = input.at(0, s);
            ++pushed_;
            ++hopCount_;
            if (pushed_ < window || hopCount_ < hop) continue;
            hopCount_ = 0;
            for (int t = 0; t < window; ++t) ordered[static_cast<size_t>(t)] = buffer_[static_cast<size_t>((pushed_ + t) % window)];
            ew::TimeSeriesView view;
            view.data = ordered.data();
            view.channels = 1;
            view.samples = static_cast<size_t>(window);
            const BinaryPulsesRegularity::Output result = feature.process(view);
            last_[0] = result.regular ? 1.0 : 0.0;
            last_[1] = result.pulseCount;
            last_[2] = result.regularityDetected ? 1.0 : 0.0;
            evaluated = true;
        }
        for (int c = 0; c < 3; ++c) out->channels[c][0] = static_cast<float>(last_[c]);
        if (!evaluated) setStatus(pushed_ < window ? Status::WarmingUp : Status::NoOutput, "");
    }

private:
    FeatureSlot<BinaryPulsesRegularity> block_;
    std::vector<double> buffer_;
    int window_ = 0;
    int pushed_ = 0;
    int hopCount_ = 0;
    double last_[3] = {0.0, 0.0, 0.0};
};

EW_TD_CHOP(BinaryPulsesRegularityCHOP, "Ewbinarypulsesregularity", "EW AP Binary Pulses Regularity", 1, 1)

// TouchDesigner Motion Noise Detector CHOP - wraps ew::motion::MotionNoiseDetector (PyEyesWeb MotionNoiseDetector)
// Noise test of a skeleton's motion: is the motion random, with jumpy speeds? For each joint the last 10 speeds are kept,
// their variance is averaged over 5 frames, and the motion is noisy when that mean exceeds Threshold. A still body, a
// uniform drift and the first 14 frames are not noisy. As in the EyesWeb block only ONE joint decides with several
// joints: the one whose name sorts last as text ("0", "1", ..., "9" before "10": joint 9 beats joint 10), once it has
// a full window; a jumpy joint with another name is not seen.
// Input: N channels, layout joint-major (j0x j0y j0z j1x ...), positions. Par "Dims" sets axes per joint. The time step
// is 1 / sample rate of the input.
// Output: 1 channel (is_noisy, 1 = noisy), one sample per input sample.
// Wiring to the Gesture Segmenter: its noise input is channel 1 of its input, non-zero = the motion is noise (blocks the
// start of a gesture). Merge the kinetic_energy channel of Kinetic Energy (channel 0) and is_noisy of this operator
// (channel 1), both computed on the same skeleton, with a Merge CHOP in this order, and connect the Merge to the
// Gesture Segmenter.
// Threshold is in squared length units of the data (PyEyesWeb: m^2 by default; its "units" scaling is not exposed:
// give the threshold in the unit of the data).
// Streaming operator (see ew_td/stream_chop.h): Source = stream keeps the speed windows between cooks, Source = clip
// starts afresh at every cook; Reset forgets the state. A sample with NaN or infinity is skipped (INVALID_INPUT, its
// output is 0, the feature does not see it).
#include <algorithm>
#include <string>
#include "ew/features/motion/motion_noise_detector.h"
#include "ew_td/plugin.h"
#include "ew_td/slot.h"
#include "ew_td/stream_chop.h"

using namespace TD;
using namespace ew_td;
using ew::motion::MotionNoiseDetector;

class MotionNoiseDetectorCHOP : public EwStreamChop {
public:
    explicit MotionNoiseDetectorCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::scalar("is_noisy")}; }

    void declareParameters(Params& p) override {
        p.page("Motion Noise Detector");
        p.integer("Dims", "Dims", 3, Range::between(1, 4));
        p.number("Threshold", "Noise Threshold (variance of speed)", 0.5, Range::slider(0.0, 5.0));
    }

    void process(CHOP_Output* out, const OP_Inputs* in, const InputView& input) override {
        const int dims = std::max(1, in->getParInt("Dims"));
        const int joints = jointCount(input, dims);

        MotionNoiseDetector::Params p;
        p.noiseThreshold = in->getParDouble("Threshold");
        for (int j = 0; j < joints; ++j) p.labels.insert(labels_[j]);
        MotionNoiseDetector& feature = feature_.get(p);

        const double dt = input.dt();
        for (int s = 0; s < out->numSamples; ++s) {
            if (skipNonFinite(input, s)) continue;
            const bool judgedQuiet = feature.process(readFrame(input, dims, s, labels_), dt);
            out->channels[0][s] = judgedQuiet ? 0.f : 1.f;
        }
    }

    void dropState() override { feature_.drop(); }

private:
    FeatureSlot<MotionNoiseDetector> feature_;
    JointLabels labels_;
};

EW_TD_CHOP(MotionNoiseDetectorCHOP, "Ewmotionnoisedetector", "EW L2 Motion Noise Detector", 1, 1)

// Readers of a CHOP input: a view over the channels, and the conversions to the core's types.
// Channel layout of a skeleton is joint-major: joint j, axis d is channel j * dims + d (x, y, z of joint 0, then joint 1...).
#pragma once
#include <cmath>
#include <memory>
#include <string>
#include <vector>
#include "CPlusPlus_Common.h"
#include "ew/common/labelled_set.h"
#include "ew/math/vec.h"
#include "ew_td/labels.h"
#include "ew_td/status.h"

namespace ew_td {

constexpr double kDefaultSampleRate = 60.0;  // used when the input reports no rate

class InputView {
public:
    explicit InputView(const TD::OP_CHOPInput* input) : input_(input) {}

    // A window the operator owns: `data` holds channel after channel, `samples` per channel.
    static InputView owned(int channels, int samples, double sampleRate, std::vector<float> data) {
        InputView view(nullptr);
        view.own_ = std::make_shared<Owned>(Owned{channels, samples, sampleRate, std::move(data)});
        return view;
    }

    // The same input seen from sample `first` on (sample 0 of the view is sample `first` of the input).
    InputView from(int first) const {
        InputView view(*this);
        view.first_ = first_ + (first > 0 ? first : 0);
        return view;
    }

    int channels() const { return own_ ? own_->channels : input_->numChannels; }
    int samples() const { return (own_ ? own_->samples : input_->numSamples) - first_; }
    double sampleRate() const {
        const double rate = own_ ? own_->sampleRate : input_->sampleRate;
        return rate > 0 ? rate : kDefaultSampleRate;
    }
    double dt() const { return 1.0 / sampleRate(); }  // seconds between two samples
    double at(int channel, int sample) const {
        if (own_) return own_->data[static_cast<size_t>(channel) * own_->samples + first_ + sample];
        return input_->getChannelData(channel)[first_ + sample];
    }

    // Whether every channel of `sample` holds a finite number (PyEyesWeb: a NaN or infinity is not data).
    bool finite(int sample) const {
        for (int c = 0; c < channels(); ++c)
            if (!std::isfinite(at(c, sample))) return false;
        return true;
    }
    // Whether the whole input is finite.
    bool finite() const {
        for (int s = 0; s < samples(); ++s)
            if (!finite(s)) return false;
        return true;
    }

private:
    struct Owned {
        int channels, samples;
        double sampleRate;
        std::vector<float> data;
    };
    const TD::OP_CHOPInput* input_;
    std::shared_ptr<const Owned> own_;
    int first_ = 0;
};

// The CHOP input `index` (null when the slot is empty or holds something else, e.g. a TOP).
inline const TD::OP_CHOPInput* chopInputOrNull(const TD::OP_Inputs* in, int index = 0) {
    return in->getNumInputs() > index ? in->getInputCHOP(index) : nullptr;
}

// The CHOP input `index`; InputError when it is not connected or is not a CHOP.
inline InputView chopInput(const TD::OP_Inputs* in, int index = 0) {
    const TD::OP_CHOPInput* input = chopInputOrNull(in, index);
    require(input != nullptr, "Input " + std::to_string(index) + " is not connected");
    return InputView(input);
}

// InputError (INVALID_INPUT, the outputs stay zero) when the input holds a NaN or an infinity: for an operator that
// takes the whole input as one frame. A sample-wise operator skips the bad sample instead: see `EwChop::skipNonFinite`.
inline void requireFinite(const InputView& view) { require(view.finite(), "input contains NaN or infinity"); }

// Sample rate of input `index` for the output, or the default when there is no such input.
inline double inputSampleRate(const TD::OP_Inputs* in, int index = 0) {
    const TD::OP_CHOPInput* input = chopInputOrNull(in, index);
    return input ? InputView(input).sampleRate() : kDefaultSampleRate;
}
// Number of samples of input `index`, or 1 when there is no such input.
inline int inputSamples(const TD::OP_Inputs* in, int index = 0) {
    const TD::OP_CHOPInput* input = chopInputOrNull(in, index);
    return input ? input->numSamples : 1;
}

// Number of joints of a joint-major input: channels / dims. InputError when the channels are not a multiple of dims.
inline int jointCount(const InputView& view, int dims) {
    require(dims >= 1, "Dims must be at least 1");
    require(view.channels() % dims == 0,
            "Input channel count (" + std::to_string(view.channels()) + ") is not a multiple of Dims (" + std::to_string(dims) + ")");
    return view.channels() / dims;
}

// Joint `joint` at `sample`; axes beyond `dims` stay 0, axes beyond 3 are ignored.
inline ew::Point3 readPoint(const InputView& view, int joint, int dims, int sample) {
    ew::Point3 p;
    if (dims > 0) p.x = view.at(joint * dims + 0, sample);
    if (dims > 1) p.y = view.at(joint * dims + 1, sample);
    if (dims > 2) p.z = view.at(joint * dims + 2, sample);
    return p;
}

// One frame of a skeleton as the core takes it: a set labelled "0", "1", ...
inline ew::LabelledSet3 readFrame(const InputView& view, int dims, int sample, JointLabels& labels) {
    const int joints = jointCount(view, dims);
    ew::LabelledSet3 set;
    for (int j = 0; j < joints; ++j) set[labels[j]] = readPoint(view, j, dims, sample);
    return set;
}

// A trajectory held as channels x, y [, z] over the samples, as the trajectory features take it: row 0 is the newest
// sample (the last one of the CHOP) when `newestFirst`. z is 0 when the input has fewer than 3 channels.
inline std::vector<ew::Point3> readTrajectory(const InputView& view, bool newestFirst = true) {
    const int n = view.samples();
    const int dims = view.channels() >= 3 ? 3 : view.channels();
    std::vector<ew::Point3> points(n);
    for (int s = 0; s < n; ++s) points[s] = readPoint(view, 0, dims, newestFirst ? n - 1 - s : s);
    return points;
}

}  // namespace ew_td

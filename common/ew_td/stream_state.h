// When the state of a streaming operator must be forgotten, and how much it has processed since. No TouchDesigner
// dependency, so the rules are tested on their own.
//
// A streaming operator keeps state from cook to cook. Its input is one of two things:
//   * a live stream (a timeslice): every sample arrives once, the state stays, the output is a timeslice too;
//   * a clip (a recording, a trail): the whole input is new at every cook, so the operator starts from a fresh state
//     each time and the output is a function of the clip alone, as PyEyesWeb `run(recording)` is.
// The state is also forgotten on request (the Reset pulse) and when the input changes its shape (another number of
// channels or another sample rate), because a state built for other data is not a state of this one.
#pragma once
#include <cmath>

namespace ew_td {

struct InputSignature {
    int channels = -1;
    double sampleRate = 0;

    bool operator==(const InputSignature& o) const {
        return channels == o.channels && std::fabs(sampleRate - o.sampleRate) <= 1e-9 * std::fabs(sampleRate);
    }
    bool operator!=(const InputSignature& o) const { return !(*this == o); }
};

enum class ResetReason { None, First, Requested, Clip, InputChanged };

inline const char* resetReasonName(ResetReason r) {
    switch (r) {
        case ResetReason::None: return "none";
        case ResetReason::First: return "first cook";
        case ResetReason::Requested: return "reset pulse";
        case ResetReason::Clip: return "clip";
        case ResetReason::InputChanged: return "input changed";
    }
    return "?";
}

class StreamState {
public:
    // The Reset pulse: the state is forgotten at the start of the next cook.
    void requestReset() { requested_ = true; }

    // Start of a cook. The reason why the state must be dropped before it, None when it is kept. `First` is reported
    // so that an operator can build its state, it is not counted as a reset.
    ResetReason begin(const InputSignature& signature, bool clip) {
        ResetReason reason = ResetReason::None;
        if (!seen_) reason = ResetReason::First;
        else if (requested_) reason = ResetReason::Requested;
        else if (signature != last_) reason = ResetReason::InputChanged;
        else if (clip) reason = ResetReason::Clip;
        requested_ = false;
        seen_ = true;
        last_ = signature;
        if (reason == ResetReason::Requested || reason == ResetReason::InputChanged) ++resets_;
        if (reason != ResetReason::None) samples_ = 0;
        lastReason_ = reason != ResetReason::None ? reason : lastReason_;
        return reason;
    }

    // End of a cook that processed `samples` samples.
    void processed(long long samples) { samples_ += samples; }

    long long samplesProcessed() const { return samples_; }  // since the last reset
    int resets() const { return resets_; }                   // by pulse or by a change of the input
    ResetReason lastReason() const { return lastReason_; }

private:
    bool requested_ = false, seen_ = false;
    InputSignature last_;
    long long samples_ = 0;
    int resets_ = 0;
    ResetReason lastReason_ = ResetReason::None;
};

}  // namespace ew_td

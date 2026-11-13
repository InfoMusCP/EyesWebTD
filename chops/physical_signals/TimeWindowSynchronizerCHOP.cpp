// TouchDesigner Time Window Synchronizer CHOP - wraps ew::base::TimeWindowSynchronizer (PyEyesWeb TimeWindowSynchronizer)
// Re-chunks one or two sampled streams into windows of the same duration [t, t + Window), t advancing by one window per
// window. Every cook appends the content of each input to its stream (an input is a live timeslice, its samples are
// the new ones; samples that do not fill a window stay for the next one), and the operator outputs the newest window
// that is complete. Use it to align two streams that arrive in chunks of different sizes and at different rates.
// PyEyesWeb has it as a plain utility class (no Result); this is its CHOP form, with the same maths. Frame streams
// (video) have no CHOP form and are not supported.
// Input 0 (and optional input 1): C0 (C1) channels at their own sample rate. A stream holds int(rate * Window) samples
// per window.
// Output: C0 + C1 channels in one buffer of max(samples per window) samples at the rate of input 0, one window per
// cook: in0_<name> for the channels of input 0 then in1_<name> for input 1. A stream whose window is shorter than the
// output is padded with zeros after its samples. When a cook completes several windows only the newest is output
// (info entry windows_popped says how many were ready: the others are dropped); when none is complete the status is
// NO_OUTPUT and the output is 0. A window that holds no sample at the rate of an input is INVALID_INPUT.
// NaN or infinity are copied through, as PyEyesWeb does (the synchronizer does not read the data).
// Window (seconds), Start Time (seconds, start of the first window) and the stream layout are structural: a change
// restarts the buffers. Buffer operator (see ew_td/buffer_chop.h): Reset forgets the buffered samples and restarts at
// Start Time. Presentation times of chunks (PyEyesWeb `timestamp`) are not used: a CHOP has no per-chunk time.
#include <algorithm>
#include <string>
#include <vector>
#include "ew/common/time_series.h"
#include "ew/features/base/time_window_synchronizer.h"
#include "ew_td/buffer_chop.h"
#include "ew_td/plugin.h"
#include "ew_td/slot.h"

using namespace TD;
using namespace ew_td;
using ew::base::TimeWindowSynchronizer;

class TimeWindowSynchronizerCHOP : public EwBufferChop {
public:
    explicit TimeWindowSynchronizerCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs* in) const override {
        Schema s;
        const int inputs = in->getNumInputs();
        for (int i = 0; i < inputs && i < 2; ++i) {
            const OP_CHOPInput* ci = in->getInputCHOP(i);
            for (int c = 0; c < ci->numChannels; ++c)
                s.add(Output::scalar("in" + std::to_string(i) + "_" + ci->getChannelName(c)));
        }
        if (s.size() == 0) s.add(Output::scalar("in0_chan0"));
        return s;
    }

    int numSamples(const OP_Inputs* in) const override {
        int most = 1;
        for (int i = 0; i < in->getNumInputs() && i < 2; ++i) most = std::max(most, samplesPerWindow(in, i));
        return most;
    }

    void declareParameters(Params& p) override {
        p.page("Time Window Synchronizer");
        p.number("Window", "Window (seconds)", 0.04, Range::atLeast(0.0001, 1.0).withSlider(0.005, 1.0));
        p.number("Starttime", "Start Time (seconds)", 0.0, Range::slider(0, 10));
    }

    void process(CHOP_Output* out, const OP_Inputs* in) override {
        const int streams = std::min(in->getNumInputs(), 2);
        require(streams >= 1, "Input 0 is not connected");
        TimeWindowSynchronizer::Params p;
        p.temporalWindow = in->getParDouble("Window");
        p.startTime = in->getParDouble("Starttime");
        std::vector<InputView> views;
        for (int i = 0; i < streams; ++i) {
            views.push_back(chopInput(in, i));
            TimeWindowSynchronizer::Input spec;
            spec.channels = views[i].channels();
            spec.samplingRate = views[i].sampleRate();
            p.inputs.push_back(spec);
        }
        TimeWindowSynchronizer& sync = sync_.get(p);

        for (int i = 0; i < streams; ++i) {
            const InputView& v = views[i];
            std::vector<double> chunk(static_cast<size_t>(v.channels()) * v.samples());
            for (int c = 0; c < v.channels(); ++c)
                for (int s = 0; s < v.samples(); ++s) chunk[static_cast<size_t>(c) * v.samples() + s] = v.at(c, s);
            sync.pushSamples(i, ew::TimeSeriesView{chunk.data(), static_cast<size_t>(v.channels()),
                                                   static_cast<size_t>(v.samples()), v.sampleRate()});
        }

        TimeWindowSynchronizer::Window latest;
        popped_ = 0;
        while (sync.ready()) {
            latest = sync.pop();
            ++popped_;
        }
        windows_ += popped_;
        if (popped_ == 0) {
            setStatus(Status::NoOutput, "no complete window yet");
            return;
        }
        lastStart_ = latest.startTime;

        int channel = 0;
        for (int i = 0; i < streams; ++i) {
            const ew::Matrix& m = latest.samples[i];
            for (size_t c = 0; c < m.rows; ++c, ++channel)
                for (size_t s = 0; s < m.cols && static_cast<int>(s) < out->numSamples; ++s)
                    out->channels[channel][s] = static_cast<float>(m(c, s));
        }
    }

    void dropState() override {
        sync_.drop();
        windows_ = 0;
    }

protected:
    void describeBuffer(Info& info) const override {
        info.number("windows_popped", popped_);
        info.number("windows_total", static_cast<double>(windows_));
        info.number("window_start", lastStart_);
    }

private:
    // int(rate * Window) as the core computes it; 1 when the parameters make no valid window (the cook then reports it).
    static int samplesPerWindow(const OP_Inputs* in, int index) {
        const OP_CHOPInput* ci = in->getInputCHOP(index);
        const double rate = ci->sampleRate > 0 ? ci->sampleRate : kDefaultSampleRate;
        const int n = static_cast<int>(rate * in->getParDouble("Window"));
        return n < 1 ? 1 : n;
    }

    FeatureSlot<TimeWindowSynchronizer> sync_;
    int popped_ = 0;
    long long windows_ = 0;
    double lastStart_ = 0;
};

EW_TD_CHOP(TimeWindowSynchronizerCHOP, "Ewtimewindowsynchronizer", "EW L1 Time Window Synchronizer", 1, 2)

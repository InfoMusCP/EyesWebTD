// Base class of an operator whose core object keeps state from cook to cook while the output is NOT one sample per
// input sample: the input is a buffer (events, a window, a grid of cells) and each cook gives one result, but what the
// object remembers (queues, an accumulated field, a ring of past samples) lives on across cooks.
// It adds the Reset pulse (page Cook): the state is forgotten at the next cook. Parameters are the concern of the
// operator, through FeatureSlot. A sample-wise operator is an EwStreamChop; an operator that keeps nothing is an EwChop.
//
// An operator implements `process` (the cook) and `dropState` (forget its feature and anything else it keeps).
#pragma once
#include <cstring>
#include "ew_td/chop_base.h"

namespace ew_td {

class EwBufferChop : public EwChop {
public:
    virtual void process(TD::CHOP_Output* out, const TD::OP_Inputs* in) = 0;
    virtual void dropState() = 0;

    void pulsePressed(const char* name, void*) override {
        if (std::strcmp(name, "Reset") == 0) resetRequested_ = true;
    }

    void describe(Info& info) const override {
        info.number("resets", resets_);
        describeBuffer(info);
    }

    void cook(TD::CHOP_Output* out, const TD::OP_Inputs* in) final {
        if (resetRequested_) {
            resetRequested_ = false;
            ++resets_;
            dropState();
        }
        process(out, in);
    }

protected:
    virtual void describeBuffer(Info&) const {}

    void declareCommonParameters(Params& p) override {
        p.page("Cook");
        p.pulse("Reset", "Reset");
    }

private:
    bool resetRequested_ = false;
    int resets_ = 0;
};

}  // namespace ew_td

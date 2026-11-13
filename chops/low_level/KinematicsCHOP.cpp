// TouchDesigner Kinematics CHOP - wraps ew::trajectory::Kinematics (Point mode)
// Savitzky-Golay smoothed derivatives of a point: smoothed position, velocity, acceleration, jerk, curvature, direction.
// Input: 1, 2 or 3 channels (x, y [, z]).
// Output: one channel per selected type (velocity, acceleration, ...) in tangential mode, one per axis
// (velocity_x, ...) in components mode; direction is always a vector (direction_x, ...). One sample per input sample.
// Streaming operator (see ew_td/stream_chop.h): Source = stream keeps the window between cooks, Source = clip starts
// afresh at every cook; Reset forgets the state.
#include <algorithm>
#include <cstring>
#include <string>
#include <vector>
#include "ew/features/trajectory/kinematics.h"
#include "ew_td/plugin.h"
#include "ew_td/slot.h"
#include "ew_td/stream_chop.h"

using namespace TD;
using namespace ew_td;
using ew::trajectory::Kinematics;

namespace {
bool components(const OP_Inputs* in) { return std::strcmp(in->getParString("Outputdims"), "components") == 0; }

std::vector<Kinematics::OutputType> selectedTypes(const OP_Inputs* in) {
    std::vector<Kinematics::OutputType> types;
    if (in->getParInt("Vel") != 0) types.push_back(Kinematics::OutputType::Velocity);
    if (in->getParInt("Acc") != 0) types.push_back(Kinematics::OutputType::Acceleration);
    if (in->getParInt("Jerk") != 0) types.push_back(Kinematics::OutputType::Jerk);
    if (in->getParInt("Curv") != 0) types.push_back(Kinematics::OutputType::Curvature);
    if (in->getParInt("Dir") != 0) types.push_back(Kinematics::OutputType::Direction);
    if (in->getParInt("Smooth") != 0) types.push_back(Kinematics::OutputType::Smoothed);
    if (types.empty()) types.push_back(Kinematics::OutputType::Velocity);
    return types;
}

const char* typeName(Kinematics::OutputType type) {
    switch (type) {
        case Kinematics::OutputType::Smoothed: return "smoothed";
        case Kinematics::OutputType::Velocity: return "velocity";
        case Kinematics::OutputType::Acceleration: return "acceleration";
        case Kinematics::OutputType::Jerk: return "jerk";
        case Kinematics::OutputType::Curvature: return "curvature";
        case Kinematics::OutputType::Direction: return "direction";
    }
    return "?";
}
}  // namespace

class KinematicsCHOP : public EwStreamChop {
public:
    explicit KinematicsCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs* in) const override {
        const int d = std::clamp(in->getNumInputs() ? in->getInputCHOP(0)->numChannels : 3, 1, 3);
        std::vector<std::string> axes{"x", "y", "z"};
        axes.resize(d);
        const bool perAxis = components(in);
        Schema s;
        for (Kinematics::OutputType type : selectedTypes(in))
            s.add(perAxis || type == Kinematics::OutputType::Direction ? Output::vector(typeName(type), axes)
                                                                       : Output::scalar(typeName(type)));
        return s;
    }

    void declareParameters(Params& p) override {
        p.page("Kinematics");
        p.menu("Outputdims", "Output Dims", "tangential",
               {{"tangential", "Tangential (Scalar Magnitude)"}, {"components", "Components (Per-Axis)"}});
        p.toggle("Vel", "Output Velocity", true);
        p.toggle("Acc", "Output Acceleration", true);
        p.toggle("Jerk", "Output Jerk", false);
        p.toggle("Curv", "Output Curvature", false);
        p.toggle("Dir", "Output Direction", false);
        p.toggle("Smooth", "Output Smoothed Pos", false);
        p.integer("Filterwindowlength", "Filter Window Length (odd)", 15, Range::atLeast(5, 51));
        p.integer("Filterpolyorder", "Filter Polyorder", 3, Range::atLeast(1, 7));
        p.number("Movementthreshold", "Movement Threshold", 0.005, Range::atLeast(0.0, 0.1));
    }

    void process(CHOP_Output* out, const OP_Inputs* in, const InputView& input) override {
        const int d = input.channels();
        require(d >= 1 && d <= 3, "Kinematics requires 1, 2, or 3 input channels");

        Kinematics::Params p;
        p.dimension = d;
        p.inputMode = Kinematics::InputMode::Point;
        p.outputDimension = components(in) ? Kinematics::OutputDimension::Components : Kinematics::OutputDimension::Tangential;
        p.outputTypes = selectedTypes(in);
        p.filterWindowLength = std::max(5, in->getParInt("Filterwindowlength"));
        if (p.filterWindowLength % 2 == 0) p.filterWindowLength += 1;
        p.filterPolyorder = std::max(1, in->getParInt("Filterpolyorder"));
        if (p.filterPolyorder >= p.filterWindowLength) p.filterPolyorder = p.filterWindowLength - 1;
        p.movementThreshold = in->getParDouble("Movementthreshold");
        Kinematics& feature = feature_.get(p);

        const double dt = input.dt();
        std::vector<double> pt(d);
        for (int s = 0; s < out->numSamples; ++s) {
            if (skipNonFinite(input, s)) continue;
            for (int k = 0; k < d; ++k) pt[k] = input.at(k, s);
            try {
                const auto outputs = feature.processPoint(pt.data(), dt);
                int channel = 0;
                for (const auto& vec : outputs)
                    for (double value : vec)
                        if (channel < out->numChannels) out->channels[channel++][s] = static_cast<float>(value);
            } catch (const std::exception& e) {
                setStatus(Status::InvalidInput, e.what());
            }
        }
    }

    void dropState() override { feature_.drop(); }

private:
    FeatureSlot<Kinematics> feature_;
};

EW_TD_CHOP(KinematicsCHOP, "Ewkinematics", "EW L2 Kinematics", 1, 1)

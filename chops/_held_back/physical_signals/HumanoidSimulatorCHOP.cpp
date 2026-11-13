// TouchDesigner Humanoid Simulator CHOP - wraps ew::humanoid::HumanoidSimulator
// A mass-spring humanoid (21 masses, 20 springs, the head is the very heavy root) that follows a captured skeleton
// (PyEyesWeb HumanoidSimulator). The simulated pose is smooth and always articulated; the translation of the person is
// not followed (the body hangs from where its head starts). Not a noise filter: see PyEyesWeb's "Known limitation".
// Input 0: 63 channels, one skeleton per sample, joint-major (joint j axis d = channel 3 * j + d) with the joints in the
// order of PyEyesWeb's HUMANOID_JOINTS (alphabetical): head, left_ankle, left_elbow, left_foot, left_hand, left_hip,
// left_knee, left_shoulder, left_wrist, neck, right_ankle, right_elbow, right_foot, right_hand, right_hip, right_knee,
// right_shoulder, right_wrist, spine, spine_base, spine_shoulder. Reorder other skeletons with a Select CHOP.
// Input 1 (optional): 60 channels, the bone directions (control) relative to the parent bone, joint-major in the order of
// PyEyesWeb's HUMANOID_BONES (the output of the Humanoid Orientations CHOP: connect it as is), the same number of
// samples as input 0. The bones follow them instead of the directions seen in the joints; a bone whose three channels
// are not all finite has no control. Without input 1 the directions are those of the joints.
// A joint with a NaN in any of its three channels is missing in that sample (a dropout the model handles: its bones stay
// as they were). An infinity, or a sample whose 63 channels are all NaN, is INVALID_INPUT: that sample is not fed to the
// model and its output stays zero.
// Output: 63 channels joints_<joint>_<x|y|z> in the order of HUMANOID_JOINTS, one sample per input sample, in Units.
// Time: each sample advances the model by 1 / (sample rate of input 0) seconds (PyEyesWeb: sampling_rate; there are no
// timestamps here), integrated in int(dt / Integrationstep) steps.
// Units: Units = m or mm is the unit of the input, of the output, of Gravity and of Floor. The core works in mm: with m
// the skeleton and the two vectors are scaled by 1000 on the way in and the joints by 1/1000 on the way out.
// Streaming operator (see ew_td/stream_chop.h): the state is the 21 masses; Source = stream keeps it between cooks,
// Source = clip starts afresh at every cook; Reset puts the body back in the T-pose. Every parameter is live (none resets
// the state). Start From Input puts the model on the first sample after a reset or a fresh state (a change applies from
// the next reset). Not exposed: labels, joint_map, the five name lists of the core, sampling_rate (the input rate).
// Deliberate difference: Integrationstep is limited to 1e-5 s or more (PyEyesWeb: any positive value) so that a mistyped
// value cannot stall TouchDesigner.
#include <cmath>
#include <cstring>
#include <string>
#include <vector>
#include "ew/features/humanoid/humanoid_simulator.h"
#include "ew_td/plugin.h"
#include "ew_td/slot.h"
#include "ew_td/stream_chop.h"

using namespace TD;
using namespace ew_td;
using ew::humanoid::HumanoidJointNames;
using ew::humanoid::HumanoidSimulator;

namespace {

constexpr int kJoints = 21;
constexpr int kBones = 20;

const std::vector<std::string>& jointNames() {
    static const std::vector<std::string> names = ew::humanoid::jointLabels(HumanoidJointNames{});
    return names;
}
const std::vector<std::string>& boneNames() {
    static const std::vector<std::string> names = ew::humanoid::boneLabels(HumanoidJointNames{});
    return names;
}

// Sample `s` as the joints the core takes (scaled by `scale`); false when it holds an infinity or only NaN.
bool readJoints(const InputView& input, int s, double scale, ew::LabelledSet3& joints) {
    bool allNaN = true;
    for (int c = 0; c < input.channels(); ++c) {
        const double v = input.at(c, s);
        if (std::isinf(v)) return false;
        if (!std::isnan(v)) allNaN = false;
    }
    if (allNaN) return false;
    joints.clear();
    for (int j = 0; j < kJoints; ++j) {
        const ew::Point3 p = readPoint(input, j, 3, s);
        if (std::isnan(p.x) || std::isnan(p.y) || std::isnan(p.z)) continue;
        joints.emplace(jointNames()[j], ew::Point3{p.x * scale, p.y * scale, p.z * scale});
    }
    return true;
}

// The bone directions of sample `s`; the bones with a non-finite component have no control.
ew::LabelledSet3 readControl(const InputView& input, int s) {
    ew::LabelledSet3 control;
    for (int b = 0; b < kBones; ++b) {
        const ew::Point3 d = readPoint(input, b, 3, s);
        if (std::isfinite(d.x) && std::isfinite(d.y) && std::isfinite(d.z)) control.emplace(boneNames()[b], d);
    }
    return control;
}

}  // namespace

class HumanoidSimulatorCHOP : public EwStreamChop {
public:
    explicit HumanoidSimulatorCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::grid("joints", jointNames(), {"x", "y", "z"})}; }

    void declareParameters(Params& p) override {
        p.page("Humanoid Simulator");
        p.menu("Units", "Units", "m", {{"m", "Metres"}, {"mm", "Millimetres"}});
        p.toggle("Startfrominput", "Start From Input", false);
        p.vector3("Refdir", "Reference Direction", {1.0, 0.0, 0.0}, Range::slider(-1, 1));
        p.number("Integrationstep", "Integration Step (s)", 0.001, Range::atLeast(1e-5, 0.01));
        p.number("Damping", "Damping", 10.0, Range::atLeast(0, 30));
        p.number("Viscosity", "Viscosity", 0.0, Range::atLeast(0, 10));
        p.toggle("Lengthforces", "Length Forces", true);
        p.toggle("Rotationforces", "Rotation Forces", true);
        p.vector3("Gravity", "Gravity", {0.0, 0.0, 0.0}, Range::slider(-20, 20));
        p.toggle("Groundinteraction", "Ground Interaction", false);
        p.vector3("Floor", "Floor Position", {0.0, 0.0, 0.0}, Range::slider(-2, 2));
    }

    void process(CHOP_Output* out, const OP_Inputs* in, const InputView& input) override {
        require(input.channels() == 3 * kJoints,
                "Input must have 63 channels (21 joints x xyz, the order of HUMANOID_JOINTS), got " + std::to_string(input.channels()));
        const bool control = in->getNumInputs() > 1 && in->getInputCHOP(1) != nullptr;
        if (control) {
            const InputView bones = chopInput(in, 1);
            require(bones.channels() == 3 * kBones, "Input 1 (control) must have 60 channels (20 bones x xyz, the order of "
                                                    "HUMANOID_BONES), got " + std::to_string(bones.channels()));
            require(bones.samples() == input.samples(), "Input 1 (control) must have as many samples as input 0");
        }

        const double scale = std::strcmp(in->getParString("Units"), "m") == 0 ? 1000.0 : 1.0;  // mm per unit of the data
        HumanoidSimulator::Params p;
        const auto refDir = vector3(in, "Refdir"), gravity = vector3(in, "Gravity"), floorPos = vector3(in, "Floor");
        p.referenceDirection = {refDir[0], refDir[1], refDir[2]};
        p.integrationStep = in->getParDouble("Integrationstep");
        p.damping = in->getParDouble("Damping");
        p.viscosity = in->getParDouble("Viscosity");
        p.lengthForces = in->getParInt("Lengthforces") != 0;
        p.rotationForces = in->getParInt("Rotationforces") != 0;
        p.gravity = {gravity[0] * scale, gravity[1] * scale, gravity[2] * scale};
        p.groundInteraction = in->getParInt("Groundinteraction") != 0;
        p.floorPosition = {floorPos[0] * scale, floorPos[1] * scale, floorPos[2] * scale};
        HumanoidSimulator& feature = feature_.get(p);

        const bool startFromInput = in->getParInt("Startfrominput") != 0;
        const double dt = input.dt();
        const std::vector<std::string>& joints = jointNames();
        ew::LabelledSet3 frame;
        for (int s = 0; s < out->numSamples; ++s) {
            if (!readJoints(input, s, scale, frame)) {
                setStatus(Status::InvalidInput, "infinite values or no joint present in the input");
                continue;
            }
            const bool teleport = startFromInput && fresh_;
            fresh_ = false;
            ew::LabelledSet3 directions;
            if (control) directions = readControl(chopInput(in, 1), s);
            const ew::LabelledSet3 result = feature.process(frame, dt, control ? &directions : nullptr, teleport);
            for (size_t j = 0; j < joints.size(); ++j) {
                const ew::Point3* q = ew::findPoint(result, joints[j]);
                out->channels[j * 3 + 0][s] = q ? static_cast<float>(q->x / scale) : NAN;
                out->channels[j * 3 + 1][s] = q ? static_cast<float>(q->y / scale) : NAN;
                out->channels[j * 3 + 2][s] = q ? static_cast<float>(q->z / scale) : NAN;
            }
        }
    }

    void dropState() override {
        feature_.drop();
        fresh_ = true;
    }

private:
    FeatureSlot<HumanoidSimulator> feature_;
    bool fresh_ = true;
};

EW_TD_CHOP(HumanoidSimulatorCHOP, "Ewhumanoidsimulator", "EW L1 Humanoid Simulator", 1, 2)

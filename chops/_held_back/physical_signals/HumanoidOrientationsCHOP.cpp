// TouchDesigner Humanoid Orientations CHOP - wraps ew::humanoid::HumanoidOrientationsExtractor
// The orientation of every bone of a 21-joint skeleton relative to its parent bone (PyEyesWeb HumanoidOrientations).
// Input: 63 channels, one skeleton per sample, joint-major (joint j axis d = channel 3 * j + d) with the joints in the
// order of PyEyesWeb's HUMANOID_JOINTS (alphabetical): head, left_ankle, left_elbow, left_foot, left_hand, left_hip,
// left_knee, left_shoulder, left_wrist, neck, right_ankle, right_elbow, right_foot, right_hand, right_hip, right_knee,
// right_shoulder, right_wrist, spine, spine_base, spine_shoulder. Reorder other skeletons with a Select CHOP.
// A joint with a NaN in any of its three channels is missing in that sample (a dropout the model handles: it keeps the
// position it had in the previous sample, the T-pose before the first). An infinity, or a sample whose 63 channels are
// all NaN, is INVALID_INPUT: that sample is not fed to the feature and its output stays zero.
// Output: 60 channels directions_<joint1>-<joint2>_<x|y|z>, the 20 bones of HUMANOID_BONES in that order, one unit
// vector per bone in the frame of its previous bone (a bone of zero length gives zero); one sample per input sample.
// Streaming operator (see ew_td/stream_chop.h): the state is the last known position of each joint. Source = stream
// keeps it between cooks, Source = clip starts afresh at every cook; Reset forgets it. Refdirx/y/z (reference direction,
// default 1 0 0; as in PyEyesWeb a zero vector is accepted) is structural: changing it starts the state afresh.
// Not exposed: labels, joint_map (the channel order is the mapping), the five name lists of the core.
#include <cmath>
#include <string>
#include <vector>
#include "ew/features/humanoid/humanoid_orientations_extractor.h"
#include "ew_td/plugin.h"
#include "ew_td/slot.h"
#include "ew_td/stream_chop.h"

using namespace TD;
using namespace ew_td;
using ew::humanoid::HumanoidJointNames;
using ew::humanoid::HumanoidOrientationsExtractor;

namespace {

constexpr int kJoints = 21;

// The joint and bone names in the order of the input and of the output (sorted, as the core keys them).
const std::vector<std::string>& jointNames() {
    static const std::vector<std::string> names = ew::humanoid::jointLabels(HumanoidJointNames{});
    return names;
}
const std::vector<std::string>& boneNames() {
    static const std::vector<std::string> names = ew::humanoid::boneLabels(HumanoidJointNames{});
    return names;
}

// Sample `s` as the joints the core takes; false (nothing built) when it holds an infinity or only NaN.
bool readJoints(const InputView& input, int s, ew::LabelledSet3& joints) {
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
        joints.emplace(jointNames()[j], p);
    }
    return true;
}

}  // namespace

class HumanoidOrientationsCHOP : public EwStreamChop {
public:
    explicit HumanoidOrientationsCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override { return {Output::grid("directions", boneNames(), {"x", "y", "z"})}; }

    void declareParameters(Params& p) override {
        p.page("Humanoid Orientations");
        p.vector3("Refdir", "Reference Direction", {1.0, 0.0, 0.0}, Range::slider(-1, 1));
    }

    void process(CHOP_Output* out, const OP_Inputs* in, const InputView& input) override {
        require(input.channels() == 3 * kJoints,
                "Input must have 63 channels (21 joints x xyz, the order of HUMANOID_JOINTS), got " + std::to_string(input.channels()));
        HumanoidOrientationsExtractor::Params p;
        const auto refDir = vector3(in, "Refdir");
        p.referenceDirection = {refDir[0], refDir[1], refDir[2]};
        HumanoidOrientationsExtractor& feature = feature_.get(p);

        const std::vector<std::string>& bones = boneNames();
        ew::LabelledSet3 joints;
        for (int s = 0; s < out->numSamples; ++s) {
            if (!readJoints(input, s, joints)) {
                setStatus(Status::InvalidInput, "infinite values or no joint present in the input");
                continue;
            }
            const ew::LabelledSet3 result = feature.process(joints);
            for (size_t b = 0; b < bones.size(); ++b) {
                const ew::Point3* d = ew::findPoint(result, bones[b]);
                out->channels[b * 3 + 0][s] = d ? static_cast<float>(d->x) : NAN;
                out->channels[b * 3 + 1][s] = d ? static_cast<float>(d->y) : NAN;
                out->channels[b * 3 + 2][s] = d ? static_cast<float>(d->z) : NAN;
            }
        }
    }

    void dropState() override { feature_.drop(); }

private:
    FeatureSlot<HumanoidOrientationsExtractor> feature_;
};

EW_TD_CHOP(HumanoidOrientationsCHOP, "Ewhumanoidorientations", "EW L1 Humanoid Orientations", 1, 1)

// TouchDesigner Silhouette Centroids CHOP - wraps ew::imaging::CentroidsCalc (PyEyesWeb SilhouetteCentroids).
// Hierarchical centroids of a human silhouette: centre of gravity, head, shoulders, elbows, forearms, hands, knees, feet.
//
// Input: a TOP holding the silhouette, named by the Top parameter (a TOP cannot be wired into a CHOP). It is a binary mask,
//   thresholded by the user before the operator (a Threshold TOP); the pixels are used as they are. The image is read as TouchDesigner gives it (one 8-bit channel,
//   first row on top), so rows run from the TOP of the image downwards as in PyEyesWeb: x to the right, y downward, in
//   pixels of the frame. A colour TOP is read through its red channel: feed it a grayscale mask.
// Output: one sample, 28 channels (the PyEyesWeb flat names, labels in the order of PyEyesWeb):
//   centroids_<label>_x, centroids_<label>_y     pixel coordinates in the frame (whole pixels), y = 0 at the top
//   Normalising (divide by the width and height of the TOP) is left to the user, after the operator.
//   <label> = center_of_gravity, head, left_shoulder, left_elbow, left_forearm, left_hand, right_shoulder, right_elbow,
//   right_forearm, right_hand, left_knee, left_foot, right_knee, right_foot. "Left" is the smaller x of the image.
//   A centroid that was not requested or cannot be found is NaN, as in PyEyesWeb.
// Parameters: Silhouette (full, upper, lower, left, right; structural), Filtercentroids, Alpha, Addintermediate, one toggle
//   per centroid (Centerofgravity, Head, Leftshoulder, ...; PyEyesWeb `parts`), Reset.
// Kind: buffer with state: the alpha filter of each centroid lives across the cooks (one frame per cook); Reset forgets it.
// Statuses: a mask without foreground is INVALID_INPUT ("no foreground pixels in the silhouette"), the outputs stay zero;
//   no TOP, or a TOP that cannot be read, is INVALID_INPUT too. Otherwise OK (no warm-up).
// Difference from PyEyesWeb: the images of TouchDesigner are floating point or 8-bit, PyEyesWeb takes 8-bit.
#include <cmath>
#include <cstring>
#include <string>
#include <vector>
#include "ew/common/blob.h"
#include "ew/common/image.h"
#include "ew/features/imaging/centroids_calc.h"
#include "ew_td/buffer_chop.h"
#include "ew_td/plugin.h"
#include "ew_td/top_mask.h"
#include "ew_td/slot.h"

using namespace TD;
using namespace ew_td;
using ew::imaging::CentroidsCalc;

namespace {

std::string channelLabel(int slot) {
    const std::string label = CentroidsCalc::centroidLabel(static_cast<CentroidsCalc::Centroid>(slot));
    return label == "cog" ? "center_of_gravity" : label;
}

}  // namespace

class SilhouetteCentroidsCHOP : public EwBufferChop {
public:
    explicit SilhouetteCentroidsCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override {
        std::vector<std::string> labels;
        for (int slot = 0; slot < CentroidsCalc::kCentroidCount; ++slot) labels.push_back(channelLabel(slot));
        return {Output::grid("centroids", labels, {"x", "y"})};
    }

    bool needsInput() const override { return false; }
    double sampleRate(const OP_Inputs*) const override { return kDefaultSampleRate; }  // there is no CHOP input to take it from

    void setupParameters(OP_ParameterManager* manager, void* reserved) override {
        OP_StringParameter top("Top");
        top.label = "TOP";
        top.page = "Silhouette";
        manager->appendTOP(top);
        EwBufferChop::setupParameters(manager, reserved);
    }

    void declareParameters(Params& p) override {
        p.page("Silhouette");
        p.menu("Silhouette", "Silhouette", "full",
               {{"full", "Full body"}, {"upper", "Upper half"}, {"lower", "Lower half"}, {"left", "Left half"}, {"right", "Right half"}});
        p.toggle("Filtercentroids", "Filter Centroids", false);
        p.number("Alpha", "Alpha", 0.75, Range::between(0, 1));
        p.toggle("Addintermediatecentroids", "Add Intermediate Centroids", false);
        p.page("Parts");
        for (const Part& part : kParts) p.toggle(part.parameter, part.label, true);
    }

    void process(CHOP_Output* out, const OP_Inputs* in) override {
        const TopMask mask(in);
        const ew::Blob2D blob = ew::blobFromMask(mask.view());

        CentroidsCalc::Params params;
        const char* silhouette = in->getParString("Silhouette");
        if (std::strcmp(silhouette, "upper") == 0) params.silhouette = CentroidsCalc::Silhouette::Upper;
        else if (std::strcmp(silhouette, "lower") == 0) params.silhouette = CentroidsCalc::Silhouette::Lower;
        else if (std::strcmp(silhouette, "left") == 0) params.silhouette = CentroidsCalc::Silhouette::Left;
        else if (std::strcmp(silhouette, "right") == 0) params.silhouette = CentroidsCalc::Silhouette::Right;
        params.computeAlpha = in->getParInt("Filtercentroids") != 0;
        params.alpha = in->getParDouble("Alpha");
        params.addComputedCentroids = in->getParInt("Addintermediatecentroids") != 0;
        auto on = [&](int slot) { return in->getParInt(kParts[slot].parameter) != 0; };
        params.centerOfGravity = on(0);
        params.head = on(1);
        params.leftShoulder = on(2);
        params.leftElbow = on(3);
        params.leftForearm = on(4);
        params.leftHand = on(5);
        params.rightShoulder = on(6);
        params.rightElbow = on(7);
        params.rightForearm = on(8);
        params.rightHand = on(9);
        params.leftKnee = on(10);
        params.leftFoot = on(11);
        params.rightKnee = on(12);
        params.rightFoot = on(13);

        const CentroidsCalc::Output result = feature_.get(params).process(blob);
        if (!result.valid) {
            setStatus(Status::InvalidInput, "no foreground pixels in the silhouette");
            return;
        }
        const int count = CentroidsCalc::kCentroidCount;
        const float nan = std::nanf("");
        for (int slot = 0; slot < count; ++slot) {
            const bool present = result.present[slot];
            out->channels[2 * slot][0] = present ? static_cast<float>(result.pixel[slot].x) : nan;
            out->channels[2 * slot + 1][0] = present ? static_cast<float>(result.pixel[slot].y) : nan;
        }
    }

    void dropState() override { feature_.drop(); }

private:
    struct Part {
        const char* parameter;
        const char* label;
    };
    // In the order of CentroidsCalc::Centroid.
    static constexpr Part kParts[CentroidsCalc::kCentroidCount] = {
        {"Centerofgravity", "Center of Gravity"}, {"Head", "Head"}, {"Leftshoulder", "Left Shoulder"}, {"Leftelbow", "Left Elbow"},
        {"Leftforearm", "Left Forearm"}, {"Lefthand", "Left Hand"}, {"Rightshoulder", "Right Shoulder"}, {"Rightelbow", "Right Elbow"},
        {"Rightforearm", "Right Forearm"}, {"Righthand", "Right Hand"}, {"Leftknee", "Left Knee"}, {"Leftfoot", "Left Foot"},
        {"Rightknee", "Right Knee"}, {"Rightfoot", "Right Foot"}};

    FeatureSlot<CentroidsCalc> feature_;
};

constexpr SilhouetteCentroidsCHOP::Part SilhouetteCentroidsCHOP::kParts[];

EW_TD_CHOP(SilhouetteCentroidsCHOP, "Ewsilhouettecentroids", "EW L1 Silhouette Centroids", 0, 0)

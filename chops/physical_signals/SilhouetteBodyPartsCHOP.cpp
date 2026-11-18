// TouchDesigner Silhouette Body Parts CHOP - wraps ew::imaging::BlobSubRegions (PyEyesWeb SilhouetteBodyParts).
// Head, trunk, arms and legs of a human silhouette, from its projection histograms.
//
// Input: a TOP holding the silhouette, named by the Top parameter (a TOP cannot be wired into a CHOP). It is a binary mask,
//   thresholded by the user before the operator (a Threshold TOP); the pixels are used as they are. Read as TouchDesigner gives it (one 8-bit channel, first row on top; see ew_td/top_mask.h):
//   rows from the TOP of the image downwards, x to the right, y downward, in pixels of the frame, as in PyEyesWeb. A
//   colour TOP is read through its red channel: feed it a grayscale mask.
// Output: one sample, 30 channels (the PyEyesWeb flat names, parts in the order left_leg, right_leg, trunk, left_arm,
//   right_arm, head; "left" is the smaller x of the image, as in Silhouette Centroids):
//   regions_<part>_x, _y, _width, _height   bounding box of the part in the frame, pixels; 0 for a part that was not found
//   is_found_<part>                         1 when the part was found, 0 otherwise
//   The per-part masks of PyEyesWeb (output `masks`) are images: they have no CHOP form and are not output. A part is
//   dropped when it is empty (EyesWeb also dropped a part touching the first column or row of the frame).
// Parameters: Armpercentage, Legssearch, Legsoffset, Armsminthreshold, Armsmaxthreshold, one toggle per part (Leftleg,
//   Rightleg, Trunk, Leftarm, Rightarm, Head; PyEyesWeb `parts`).
// Kind: frame (the block keeps nothing between cooks), so there is no Reset.
// Statuses: a mask without foreground is INVALID_INPUT ("no foreground pixels in the silhouette"), the outputs stay zero;
//   no TOP, or a TOP that cannot be read, is INVALID_INPUT too. Otherwise OK (no warm-up).
#include <cstring>
#include <string>
#include <vector>
#include "ew/common/blob.h"
#include "ew/common/image.h"
#include "ew/features/imaging/blob_sub_regions.h"
#include "ew_td/chop_base.h"
#include "ew_td/plugin.h"
#include "ew_td/top_mask.h"

using namespace TD;
using namespace ew_td;
using ew::imaging::BlobSubRegions;

namespace {

constexpr int kPartCount = 6;

}  // namespace

class SilhouetteBodyPartsCHOP : public EwChop {
public:
    explicit SilhouetteBodyPartsCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs*) const override {
        std::vector<std::string> labels;
        for (const Part& part : kParts) labels.push_back(part.label);
        return {Output::grid("regions", labels, {"x", "y", "width", "height"}), Output::vector("is_found", labels)};
    }

    bool needsInput() const override { return false; }
    double sampleRate(const OP_Inputs*) const override { return kDefaultSampleRate; }  // there is no CHOP input to take it from

    void setupParameters(OP_ParameterManager* manager, void* reserved) override {
        OP_StringParameter top("Top");
        top.label = "TOP";
        top.page = "Silhouette";
        manager->appendTOP(top);
        EwChop::setupParameters(manager, reserved);
    }

    void declareParameters(Params& p) override {
        p.page("Silhouette");
        p.number("Armpercentage", "Arm Percentage", 0.8, Range::atLeast(0, 1));
        p.number("Legssearch", "Legs Search", 0.5, Range::atLeast(0, 1));
        p.number("Legsoffset", "Legs Offset", 0.2, Range::atLeast(0, 1));
        p.number("Armsminthreshold", "Arms Min Threshold", 0.2, Range::atLeast(0, 1));
        p.number("Armsmaxthreshold", "Arms Max Threshold", 0.5, Range::atLeast(0, 1));
        p.page("Parts");
        for (const Part& part : kParts) p.toggle(part.parameter, part.title, true);
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const TopMask mask(in);
        const ew::Blob2D blob = ew::blobFromMask(mask.view());
        if (blob.mask.empty()) {
            setStatus(Status::InvalidInput, "no foreground pixels in the silhouette");
            return;
        }

        BlobSubRegions::Params params;
        params.armPercentage = in->getParDouble("Armpercentage");
        params.legsSearch = in->getParDouble("Legssearch");
        params.legsOffset = in->getParDouble("Legsoffset");
        params.armsMinThreshold = in->getParDouble("Armsminthreshold");
        params.armsMaxThreshold = in->getParDouble("Armsmaxthreshold");
        // The core names its slots by the subject's sides: its Right* parts are on the smaller x, the image's left.
        params.extractRightLeg = in->getParInt("Leftleg") != 0;
        params.extractLeftLeg = in->getParInt("Rightleg") != 0;
        params.extractTrunk = in->getParInt("Trunk") != 0;
        params.extractRightArm = in->getParInt("Leftarm") != 0;
        params.extractLeftArm = in->getParInt("Rightarm") != 0;
        params.extractHead = in->getParInt("Head") != 0;

        const BlobSubRegions block(params);
        for (const BlobSubRegions::SubRegion& region : block.process(blob)) {
            const int slot = static_cast<int>(region.part);
            out->channels[4 * slot + 0][0] = static_cast<float>(region.blob.origin.x);
            out->channels[4 * slot + 1][0] = static_cast<float>(region.blob.origin.y);
            out->channels[4 * slot + 2][0] = static_cast<float>(region.blob.mask.width);
            out->channels[4 * slot + 3][0] = static_cast<float>(region.blob.mask.height);
            out->channels[4 * kPartCount + slot][0] = 1.f;
        }
    }

private:
    struct Part {
        const char* label;      // PyEyesWeb name
        const char* parameter;  // toggle
        const char* title;
    };
    // In the order of BlobSubRegions::BodyPart, named by the image's sides (the core's RightLeg slot is the left leg).
    static constexpr Part kParts[kPartCount] = {{"left_leg", "Leftleg", "Left Leg"}, {"right_leg", "Rightleg", "Right Leg"},
                                                {"trunk", "Trunk", "Trunk"},         {"left_arm", "Leftarm", "Left Arm"},
                                                {"right_arm", "Rightarm", "Right Arm"}, {"head", "Head", "Head"}};
};

constexpr SilhouetteBodyPartsCHOP::Part SilhouetteBodyPartsCHOP::kParts[];

EW_TD_CHOP(SilhouetteBodyPartsCHOP, "Ewsilhouettebodyparts", "EW L1 Silhouette Body Parts", 0, 0)

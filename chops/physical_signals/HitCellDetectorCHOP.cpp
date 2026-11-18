// TouchDesigner Hit Cell Detector CHOP - wraps ew::space::HitCellDetector
// Input: 2 channels (x, y) representing 2D points.
// Output: 2 channels (cell_row, cell_col): the row and column of the cell that a point hits. Stream (default): one sample,
// the cell of the newest point, whatever number of points the live source gives in a frame. Clip: one per input sample.
// The cell is -1 when there is none: every point (status INVALID_INPUT) when Clip Values is off and a point is outside the
// area, as the core rejects the whole call, and when the input cannot be read or has a NaN or infinite value.
#include <vector>
#include "ew/features/space/hit_cell_detector.h"
#include "ew/math/vec.h"
#include "ew_td/plugin.h"
#include "ew_td/sample_chop.h"

using namespace TD;
using namespace ew_td;
using ew::Point2;
using ew::space::HitCellDetector;

class HitCellDetectorCHOP : public EwSampleChop {
public:
    explicit HitCellDetectorCHOP(const OP_NodeInfo*) {}

    // The cell channels have the names the operator always had: PyEyesWeb has no fixed names for a list of cells.
    Schema schema(const OP_Inputs*) const override { return {Output::scalar("cell_row"), Output::scalar("cell_col")}; }

    bool oneSampleInStream() const override { return true; }


    void declareParameters(Params& p) override {
        p.page("Hit Cell Detector");
        p.integer("Cellsalongx", "Cells Along X", 10, Range::atLeast(1, 100));
        p.integer("Cellsalongy", "Cells Along Y", 10, Range::atLeast(1, 100));
        p.number("Xmin", "X Min", 0.0, Range::slider(0, 1));
        p.number("Xmax", "X Max", 1.0, Range::slider(0, 1));
        p.number("Ymin", "Y Min", 0.0, Range::slider(0, 1));
        p.number("Ymax", "Y Max", 1.0, Range::slider(0, 1));
        p.toggle("Clipvalues", "Clip Values", true);
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        for (int c = 0; c < 2; ++c)
            for (int s = 0; s < out->numSamples; ++s) out->channels[c][s] = -1.f;
        if (!checkSlice(out, in)) return;

        const InputView input = chopInput(in);
        if (input.channels() < 2) {
            setStatus(Status::InvalidInput, "Requires at least 2 channels (x, y)");
            return;
        }
        require(input.samples() > 0, "the input has no samples");
        const int first = singleSample(in) ? newestSample(in) : 0;
        if (first == 0 ? !input.finite() : !input.finite(first)) {
            setStatus(Status::InvalidInput, "input contains NaN or infinity");
            return;
        }

        HitCellDetector::Params p;
        p.cellsAlongX = in->getParInt("Cellsalongx");
        p.cellsAlongY = in->getParInt("Cellsalongy");
        p.xMin = in->getParDouble("Xmin");
        p.xMax = in->getParDouble("Xmax");
        p.yMin = in->getParDouble("Ymin");
        p.yMax = in->getParDouble("Ymax");
        p.clipValues = in->getParInt("Clipvalues") != 0;

        // Stream: one sample out, the cell of the newest point (a live source gives 1 or 2 points in a frame); Clip: one
        // cell for every point of the recording.
        std::vector<Point2> points(input.samples() - first);
        for (int s = first; s < input.samples(); ++s) {
            points[s - first].x = input.at(0, s);
            points[s - first].y = input.at(1, s);
        }

        const auto res = HitCellDetector(p).process(points);
        if (!res.has_value()) {
            setStatus(Status::InvalidInput, "point out of range (clip_values is off)");
            return;
        }
        const auto& cells = *res;
        for (size_t s = 0; s < cells.size() && static_cast<int>(s) < out->numSamples; ++s) {
            out->channels[0][s] = static_cast<float>(cells[s].i);
            out->channels[1][s] = static_cast<float>(cells[s].j);
        }
    }
};

EW_TD_CHOP(HitCellDetectorCHOP, "Ewhitcelldetector", "EW L1 Hit Cell Detector", 1, 1)

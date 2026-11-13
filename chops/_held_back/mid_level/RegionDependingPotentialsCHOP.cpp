// TouchDesigner Region Depending Potentials CHOP - wraps ew::space::RegionDependingPotentials
// Input: 2 channels (cell_row, cell_col; cells outside the grid are ignored) or 1 channel (region_index).
// Output: CellsY channels (row_0 ...) x CellsX samples containing the 2D potential field.
// A cook with no usable cell is NO_OUTPUT and shows the last field again; an error of the core (a region index out of
// range, ...) is INVALID_INPUT.
// Buffer with state: the region values accumulate over the cooks; Reset forgets them.
#include <cstring>
#include <optional>
#include <vector>
#include "ew/common/matrix.h"
#include "ew/features/space/region_depending_potentials.h"
#include "ew_td/buffer_chop.h"
#include "ew_td/plugin.h"
#include "ew_td/slot.h"

using namespace TD;
using namespace ew_td;
using ew::space::Cell;
using ew::space::RegionDependingPotentials;

class RegionDependingPotentialsCHOP : public EwBufferChop {
public:
    explicit RegionDependingPotentialsCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs* in) const override {
        const int cy = in->getParInt("Cellsy");
        return {Output::indexed("row", cy > 0 ? cy : 10)};
    }

    int numSamples(const OP_Inputs* in) const override {
        const int cx = in->getParInt("Cellsx");
        return cx > 0 ? cx : 10;
    }

    void declareParameters(Params& p) override {
        p.page("Region Potentials");
        p.menu("Potentialtype", "Potential Type", "incdec",
               {{"incdec", "Increment / Decrement"}, {"linear", "Linear Occupation Rates"},
                {"exponential", "Exponential Occupation Rates"}});
        p.integer("Cellsx", "Grid Width (Cols X)", 10, Range::atLeast(1, 100));
        p.integer("Cellsy", "Grid Height (Rows Y)", 10, Range::atLeast(1, 100));
        p.integer("Numregions", "Number of Regions", 4, Range::atLeast(1, 32));
        p.number("Inc", "Increment Factor", 1.0, Range::slider(0, 1));
        p.number("Dec", "Decrement Factor", 0.1, Range::slider(0, 1));
    }

    void process(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        require(input.channels() >= 1, "Requires 1 channel (region_index) or 2 (cell_row, cell_col)");
        requireFinite(input);
        const bool useRegions = input.channels() < 2;

        RegionDependingPotentials::Params p;
        p.cellsAlongX = in->getParInt("Cellsx");
        p.cellsAlongY = in->getParInt("Cellsy");
        p.numberOfRegions = in->getParInt("Numregions");
        p.inputKind = useRegions ? RegionDependingPotentials::InputKind::HitRegions
                                 : RegionDependingPotentials::InputKind::Cells;
        const char* type = in->getParString("Potentialtype");
        if (std::strcmp(type, "linear") == 0) p.potentialType = RegionDependingPotentials::PotentialType::OccupationRatesLinear;
        else if (std::strcmp(type, "exponential") == 0) p.potentialType = RegionDependingPotentials::PotentialType::OccupationRatesExponential;
        else p.potentialType = RegionDependingPotentials::PotentialType::IncrementDecrement;
        p.incrementFactor = in->getParDouble("Inc");
        p.decrementFactor = in->getParDouble("Dec");
        p.outputPotentialMatrix = true;

        RegionDependingPotentials& feature = feature_.get(p);

        RegionDependingPotentials::Output res;
        if (useRegions) {
            std::vector<int> regions;
            for (int s = 0; s < input.samples(); ++s) regions.push_back(static_cast<int>(input.at(0, s)));
            res = feature.process(regions);
        } else {
            std::vector<Cell> hitCells;
            for (int s = 0; s < input.samples(); ++s) {
                const int r = static_cast<int>(input.at(0, s));
                const int c = static_cast<int>(input.at(1, s));
                if (r >= 0 && r < p.cellsAlongY && c >= 0 && c < p.cellsAlongX) hitCells.push_back(Cell{r, c});
            }
            res = feature.process(hitCells);
        }
        if (!res.error.empty()) {
            setStatus(Status::InvalidInput, res.error);
            return;
        }
        if (!res.potential.has_value()) {
            setStatus(Status::NoOutput, "no cell hit");
            if (held_.has_value()) show(out, *held_);
            return;
        }
        held_ = *res.potential;
        show(out, *held_);
    }

    void dropState() override {
        feature_.drop();
        held_.reset();
    }

private:
    static void show(CHOP_Output* out, const ew::Matrix& mat) {
        for (size_t r = 0; r < mat.rows && static_cast<int>(r) < out->numChannels; ++r)
            for (size_t c = 0; c < mat.cols && static_cast<int>(c) < out->numSamples; ++c)
                out->channels[r][c] = static_cast<float>(mat(r, c));
    }

    FeatureSlot<RegionDependingPotentials> feature_;
    std::optional<ew::Matrix> held_;
};

EW_TD_CHOP(RegionDependingPotentialsCHOP, "Ewregiondependingpotentials", "EW L3 Region Depending Potentials", 1, 1)

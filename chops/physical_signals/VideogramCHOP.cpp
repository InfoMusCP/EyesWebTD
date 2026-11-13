// TouchDesigner Videogram CHOP - wraps ew::imaging::VideoGram (PyEyesWeb Videogram).
// Every frame is collapsed to one line (the mean of each row, or of each column, truncated) and the
// lines of successive frames are stacked over time: a movement becomes a visible trace (a motiongram for a motion image).
//
// Input: a TOP, one frame per cook. The TOP is the wired input 0 when it is a TOP, otherwise the TOP named by the Top
//   parameter. It is read as TouchDesigner gives it (8-bit, verticalFlip), rows from the TOP of the image downwards as in
//   PyEyesWeb; Channels picks what is read: gray (Mono8Fixed: the red channel of a colour TOP, so feed a grayscale
//   TOP), rgb or rgba (each channel summed and scaled on its own, as PyEyesWeb does for colour frames).
// Output (a CHOP cannot hold an image, so the videogram image of PyEyesWeb is carried as its time series): `Window`
//   samples (the lines of the image, in the order of the image: sample s is column s of a horizontal videogram, row s of
//   a vertical one) and one channel per position along the line, in the same order as the image axis:
//     horizontal: videogram_<h>        (gray) or videogram_<h>_<r|g|b|a>   h = row of the frame, 0 = top
//     vertical:   videogram_<w>        (gray) or videogram_<w>_<r|g|b|a>   w = column of the frame, 0 = left
//   so channel <h> at sample s is image[h, s] of PyEyesWeb's (H, window, C) array (vertical: channel <w> at sample s is
//   image[s, w] of (window, W, C)). Values are the integers 0-255 of PyEyesWeb. Lines not written yet are 0. The number
//   of channels is the frame height (or width) times the colour channels: 1080 channels for a full HD gray frame.
// Parameters: Window, Mode (horizontal, vertical; structural), Direction, Endofimagemode (loop, scroll), Channels, Reset.
// Kind: buffer with state: the image (and its write position) lives across the cooks, one frame per cook; Reset clears it.
//   A frame of another size or channel count restarts the videogram; the status is OK, the reason says so, as PyEyesWeb.
// Statuses: no TOP, or a TOP that cannot be read, is INVALID_INPUT. Otherwise OK (no warm-up).
#include <cstring>
#include <string>
#include <vector>
#include "ew/common/image.h"
#include "ew/features/imaging/videogram.h"
#include "ew_td/buffer_chop.h"
#include "ew_td/plugin.h"
#include "ew_td/slot.h"

using namespace TD;
using namespace ew_td;
using ew::imaging::VideoGram;

namespace {

const OP_TOPInput* topOf(const OP_Inputs* in) {
    const OP_TOPInput* top = in->getNumInputs() > 0 ? in->getInputTOP(0) : nullptr;
    return top ? top : in->getParTOP("Top");
}

int colourChannels(const OP_Inputs* in) {
    const char* channels = in->getParString("Channels");
    return std::strcmp(channels, "rgba") == 0 ? 4 : std::strcmp(channels, "rgb") == 0 ? 3 : 1;
}

// The frame as an 8-bit image (1, 3 or 4 channels, RGB order), first row on top.
ew::Image readFrame(const OP_TOPInput* top, int channels) {
    OP_TOPInputDownloadOptions options;
    options.verticalFlip = true;
    options.pixelFormat = channels == 1 ? OP_PixelFormat::Mono8Fixed : OP_PixelFormat::BGRA8Fixed;
    OP_SmartRef<OP_TOPDownloadResult> result = top->downloadTexture(options, nullptr);
    require(static_cast<bool>(result), "the TOP could not be read");
    const OP_TextureDesc& desc = result->textureDesc;
    const int width = static_cast<int>(desc.width), height = static_cast<int>(desc.height);
    require(desc.texDim == OP_TexDim::e2D && width > 0 && height > 0, "the TOP is not a 2D image");
    require(desc.pixelFormat == options.pixelFormat, "the TOP was not given in the requested pixel format");
    const size_t pixelCount = static_cast<size_t>(width) * height;
    const unsigned char* pixels = static_cast<const unsigned char*>(result->getData());
    require(pixels != nullptr && result->size >= pixelCount * (channels == 1 ? 1 : 4), "the TOP has no pixel data");
    ew::Image frame(width, height, channels);
    if (channels == 1) {
        std::memcpy(frame.data.data(), pixels, pixelCount);
    } else {
        for (size_t i = 0; i < pixelCount; ++i) {  // BGRA -> RGB[A]
            unsigned char* dst = frame.data.data() + i * channels;
            dst[0] = pixels[4 * i + 2];
            dst[1] = pixels[4 * i + 1];
            dst[2] = pixels[4 * i + 0];
            if (channels == 4) dst[3] = pixels[4 * i + 3];
        }
    }
    return frame;
}

}  // namespace

class VideogramCHOP : public EwBufferChop {
public:
    explicit VideogramCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs* in) const override {
        const OP_TOPInput* top = topOf(in);
        const int channels = colourChannels(in);
        int bins = 1;
        if (top) {
            const bool horizontal = std::strcmp(in->getParString("Mode"), "vertical") != 0;
            bins = static_cast<int>(horizontal ? top->textureDesc.height : top->textureDesc.width);
            if (bins < 1) bins = 1;
        }
        if (channels == 1) return {Output::indexed("videogram", bins)};
        std::vector<std::string> positions;
        for (int i = 0; i < bins; ++i) positions.push_back(std::to_string(i));
        std::vector<std::string> colours = {"r", "g", "b"};
        if (channels == 4) colours.push_back("a");
        return {Output::grid("videogram", positions, colours)};
    }

    int numSamples(const OP_Inputs* in) const override {
        const int window = in->getParInt("Window");
        return window > 0 ? window : 1;
    }

    bool needsInput() const override { return false; }
    double sampleRate(const OP_Inputs*) const override { return kDefaultSampleRate; }  // there is no CHOP input to take it from

    void setupParameters(OP_ParameterManager* manager, void* reserved) override {
        OP_StringParameter top("Top");
        top.label = "TOP";
        top.page = "Videogram";
        manager->appendTOP(top);
        EwBufferChop::setupParameters(manager, reserved);
    }

    void declareParameters(Params& p) override {
        p.page("Videogram");
        p.integer("Window", "Window (Lines)", 500, Range::atLeast(1, 1000));
        p.menu("Mode", "Mode", "horizontal", {{"horizontal", "Horizontal (sum of each row)"}, {"vertical", "Vertical (sum of each column)"}});
        p.menu("Direction", "Direction", "left_to_right", {{"left_to_right", "Left to Right"}, {"right_to_left", "Right to Left"}});
        p.menu("Endofimagemode", "End of Image Mode", "loop", {{"loop", "Loop"}, {"scroll", "Scroll"}});
        p.menu("Channels", "Channels", "gray", {{"gray", "Gray"}, {"rgb", "RGB"}, {"rgba", "RGBA"}});
    }

    void process(CHOP_Output* out, const OP_Inputs* in) override {
        const OP_TOPInput* top = topOf(in);
        require(top != nullptr, "no TOP: set the Top parameter (or wire a TOP) to the frames");
        const int channels = colourChannels(in);
        const ew::Image frame = readFrame(top, channels);

        VideoGram::Params params;
        params.window = in->getParInt("Window");
        params.mode = std::strcmp(in->getParString("Mode"), "vertical") == 0 ? VideoGram::Mode::Vertical : VideoGram::Mode::Horizontal;
        params.direction = std::strcmp(in->getParString("Direction"), "right_to_left") == 0 ? VideoGram::Direction::RightToLeft
                                                                                            : VideoGram::Direction::LeftToRight;
        params.endOfImageMode = std::strcmp(in->getParString("Endofimagemode"), "scroll") == 0 ? VideoGram::EndOfImageMode::Scroll
                                                                                              : VideoGram::EndOfImageMode::Loop;
        VideoGram& feature = feature_.get(params);

        const Shape shape{frame.width, frame.height, frame.channels};
        if (hasShape_ && !(shape == shape_)) {
            feature.reset();
            setStatus(Status::Ok, "frame size changed: videogram restarted");
        }
        shape_ = shape;
        hasShape_ = true;

        const ew::Image& image = feature.process(frame.view());
        const bool horizontal = params.mode == VideoGram::Mode::Horizontal;
        const int bins = horizontal ? image.height : image.width;
        const int lines = horizontal ? image.width : image.height;
        for (int bin = 0; bin < bins; ++bin)
            for (int c = 0; c < image.channels; ++c) {
                const int channel = bin * image.channels + c;
                if (channel >= out->numChannels) continue;
                for (int line = 0; line < lines && line < out->numSamples; ++line)
                    out->channels[channel][line] = static_cast<float>(horizontal ? image.at(line, bin, c) : image.at(bin, line, c));
            }
        writePosition_ = feature.writePosition();
    }

    void dropState() override {
        feature_.drop();
        hasShape_ = false;
        writePosition_ = 0;
    }

protected:
    void describeBuffer(Info& info) const override {
        info.number("frame_width", hasShape_ ? shape_.width : 0);
        info.number("frame_height", hasShape_ ? shape_.height : 0);
        info.number("write_position", writePosition_);
    }

private:
    struct Shape {
        int width = 0, height = 0, channels = 0;
        bool operator==(const Shape& o) const { return width == o.width && height == o.height && channels == o.channels; }
    };

    FeatureSlot<VideoGram> feature_;
    Shape shape_;
    bool hasShape_ = false;
    int writePosition_ = 0;
};

EW_TD_CHOP(VideogramCHOP, "Ewvideogram", "EW L1 Videogram", 0, 1)

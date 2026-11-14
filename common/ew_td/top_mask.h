// The silhouette of a TOP as an 8-bit mask, for the operators that read an image (Silhouette Centroids, Body Parts).
//
// The TOP is downloaded as one 8-bit channel (a quarter of the bytes of a 32-bit float image, which is most of the time
// of an operator at video sizes). A pixel is foreground when its value, in the 0-1 range of the TOP, is above the
// threshold; at threshold 0 that is "non-zero", so the downloaded bytes are the mask and nothing is copied. Otherwise the
// mask is built in one pass. The pixels are read with the first row on top, as in PyEyesWeb.
//
// Difference from reading a 32-bit float image: a value of a floating-point TOP below 1/510 rounds to 0 in the 8-bit
// download, so it is background at any threshold.
#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>
#include "ew/common/image.h"
#include "ew_td/plugin.h"

namespace ew_td {

class TopMask {
public:
    // `top` is the wired input 0 when it is a TOP, otherwise the TOP of the `Top` parameter.
    static const TD::OP_TOPInput* topOf(const TD::OP_Inputs* in) {
        const TD::OP_TOPInput* top = in->getNumInputs() > 0 ? in->getInputTOP(0) : nullptr;
        return top ? top : in->getParTOP("Top");
    }

    TopMask(const TD::OP_Inputs* in, double threshold) {
        const TD::OP_TOPInput* top = topOf(in);
        require(top != nullptr, "no TOP: set the Top parameter (or wire a TOP) to the silhouette");
        TD::OP_TOPInputDownloadOptions options;
        options.verticalFlip = true;
        options.pixelFormat = TD::OP_PixelFormat::Mono8Fixed;
        download_ = top->downloadTexture(options, nullptr);
        require(static_cast<bool>(download_), "the TOP could not be read");
        const TD::OP_TextureDesc& desc = download_->textureDesc;
        const int width = static_cast<int>(desc.width), height = static_cast<int>(desc.height);
        require(desc.texDim == TD::OP_TexDim::e2D && width > 0 && height > 0, "the TOP is not a 2D image");
        require(desc.pixelFormat == options.pixelFormat, "the TOP was not given in the requested pixel format");
        const std::size_t count = static_cast<std::size_t>(width) * static_cast<std::size_t>(height);
        const std::uint8_t* pixels = static_cast<const std::uint8_t*>(download_->getData());
        require(pixels != nullptr && download_->size >= count, "the TOP has no pixel data");
        if (threshold <= 0.0) {
            view_ = ew::ImageView{pixels, width, height, 1, 0};  // any non-zero pixel is body: no copy
            return;
        }
        const double limit = threshold * 255.0;
        copy_.resize(count);
        for (std::size_t i = 0; i < count; ++i) copy_[i] = pixels[i] > limit ? 255 : 0;
        view_ = ew::ImageView{copy_.data(), width, height, 1, 0};
    }

    // Valid while this object lives.
    const ew::ImageView& view() const { return view_; }

private:
    TD::OP_SmartRef<TD::OP_TOPDownloadResult> download_;
    std::vector<std::uint8_t> copy_;
    ew::ImageView view_;
};

}  // namespace ew_td

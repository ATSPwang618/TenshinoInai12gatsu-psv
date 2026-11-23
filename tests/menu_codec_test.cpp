#include "media.hpp"
#include <iostream>
// Independent consumer: round-trip tests must pass the actual native decoder,
// not merely two Python functions with the same mistake.
int main(int argc, char **argv) {
    try {
        if (argc != 3)
            throw std::runtime_error("Expected fixture archive and raw output");
        tenshi::Archive archive(argv[1]);
        auto atlas = tenshi::lzss(archive.read("test.px"));
        auto pixels = tenshi::pxFrame(atlas, 0);
        std::ofstream out(argv[2], std::ios::binary);
        out.write(reinterpret_cast<const char *>(pixels.rgba.data()), pixels.rgba.size());
        if (!out)
            throw std::runtime_error("Cannot write decoded test pixels");
        std::cout << pixels.w << ' ' << pixels.h << ' ' << pixels.x << ' ' << pixels.y << '\n';
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}

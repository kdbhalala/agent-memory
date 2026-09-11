class AgiMemory < Formula
  include Language::Python::Virtualenv

  desc "Turnkey zero-dependency two-layer memory architecture for AI coding assistants"
  homepage "https://github.com/kdbhalala/agi-memory"
  url "https://github.com/kdbhalala/agi-memory/archive/refs/tags/v0.1.1.tar.gz"
  sha256 "7818fff41e03990b763144257b0312357667a5046979957d9f4dfc50f4da4365"
  license "MIT"
  head "https://github.com/kdbhalala/agi-memory.git", branch: "main"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "agi-memory 0.1.1", shell_output("#{bin}/agi-memory --version")
    assert_match "Turnkey integration tool", shell_output("#{bin}/agi-integrate --help")
    assert_match "Recall from agent session", shell_output("#{bin}/agi-recall --help")
  end
end

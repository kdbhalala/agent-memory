class AgentMemory < Formula
  include Language::Python::Virtualenv

  desc "Turnkey zero-dependency two-layer memory architecture for AI coding assistants"
  homepage "https://github.com/kdbhalala/agi-memory"
  url "https://github.com/kdbhalala/agi-memory/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "a73797b1e99c15ffdc909ee8c1e44bb0ff2ded6e232e4be6ae19289f5b0bc0ee"
  license "MIT"
  head "https://github.com/kdbhalala/agi-memory.git", branch: "main"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "agent-memory 0.1.0", shell_output("#{bin}/agent-memory --version")
    assert_match "Turnkey integration tool", shell_output("#{bin}/agent-integrate --help")
    assert_match "Recall from agent session", shell_output("#{bin}/agent-recall --help")
  end
end

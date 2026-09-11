class AgentMemory < Formula
  include Language::Python::Virtualenv

  desc "Turnkey zero-dependency two-layer memory architecture for AI coding assistants"
  homepage "https://github.com/kdbhalala/agent-memory"
  url "https://github.com/kdbhalala/agent-memory/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "604e389a178aa2e1615060aa4dad7c0e3740da9ff3aaf8fcf14b684914a1abee"
  license "MIT"
  head "https://github.com/kdbhalala/agent-memory.git", branch: "main"

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

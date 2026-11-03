type Node = { type: string; value?: string; children?: Node[] };

const isImage = (node: Node) => node.type === "image" || node.type === "imageReference";
const containsImage = (node: Node): boolean => isImage(node) || !!node.children?.some(containsImage);
const hasContent = (node: Node): boolean => !!node.value?.trim() || !!node.children?.some(hasContent);

/** Remove model-supplied image URLs and tables that only served to arrange them. */
export default function remarkNoImages() {
  return function clean(node: Node) {
    if (!node.children) return;
    node.children = node.children.filter((child) => {
      if (isImage(child)) return false;
      const hadImages = containsImage(child);
      clean(child);
      if (hadImages && child.type === "paragraph" && !hasContent(child)) return false;
      if (hadImages && child.type === "table" && !child.children?.slice(1).some(hasContent)) return false;
      return true;
    });
  };
}
